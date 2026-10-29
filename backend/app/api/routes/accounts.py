import json
from contextlib import contextmanager
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_cookie, encrypt_cookie
from app.core.deps import get_current_user, get_db, now_utc
from app.crud.accounts import add as add_account
from app.crud.accounts import count_valid, get_for_user, list_for_user
from app.models import (
    DownloadTask,
    Job,
    PanAccount,
    ShareLink,
    ShareStatSnapshot,
    UploadTask,
    User,
)
from app.services.baidu_login_sessions import LoginSessionStore
from app.services.membership import account_limit
from app.pans import LoginRejected, ProviderClosed, adapter_for
from app.pans.baidu_login import QrLoginFailed, poll_qr, start_qr
from app.pans.quark_login import QrLoginFailed as QuarkQrLoginFailed
from app.pans.quark_login import poll_qr as poll_quark_qr
from app.pans.quark_login import start_qr as start_quark_qr
from app.pans.xunlei_login import QrLoginFailed as XunleiQrLoginFailed
from app.pans.xunlei_login import poll_qr as poll_xunlei_qr
from app.pans.xunlei_login import start_qr as start_xunlei_qr
from app.schemas import (
    AccountBindIn,
    AccountCookieIn,
    AccountOut,
    BaiduLoginOut,
    BaiduLoginStartIn,
)

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def get_pan_http_client(request: Request) -> httpx.Client:
    client = getattr(request.app.state, "pan_http_client", None)
    if client is None:
        client = httpx.Client()
        request.app.state.pan_http_client = client
    return client


def get_login_store(request: Request) -> LoginSessionStore:
    store = getattr(request.app.state, "baidu_login_sessions", None)
    if store is None:
        store = LoginSessionStore()
        request.app.state.baidu_login_sessions = store
    return store


@contextmanager
def pan_client(request: Request):
    existing = getattr(request.app.state, "pan_http_client", None)
    if existing is not None:
        yield existing
        return
    client = httpx.Client()
    try:
        yield client
    finally:
        client.close()


def owned_account(session: Session, user: User, account_id: int) -> PanAccount:
    account = get_for_user(session, user.id, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    if account.provider != "baidu":
        raise HTTPException(status_code=422, detail="暂未开放")
    return account


def to_account_out(
    account: PanAccount, last_synced_at: datetime | None = None
) -> AccountOut:
    return AccountOut(
        id=account.id,
        provider=account.provider,
        nickname=account.nickname,
        status=account.status,
        created_at=account.created_at,
        updated_at=account.updated_at,
        last_synced_at=last_synced_at,
    )


def _last_sync_map(session: Session, account_ids: list[int]) -> dict[int, datetime]:
    if not account_ids:
        return {}
    rows = session.execute(
        select(Job.account_id, func.max(Job.updated_at))
        .where(
            Job.account_id.in_(account_ids),
            Job.type == "sync",
            Job.status == "succeeded",
        )
        .group_by(Job.account_id)
    ).all()
    return {account_id: moment for account_id, moment in rows if account_id is not None}


def xunlei_subject(cookie: str) -> str | None:
    try:
        payload = json.loads(cookie)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    subject = payload.get("user_id")
    return subject if isinstance(subject, str) and subject else None


def same_xunlei_account(
    session: Session, user: User, cookie: str, key: str
) -> PanAccount | None:
    subject = xunlei_subject(cookie)
    if subject is None:
        return None
    matches: list[PanAccount] = []
    for account in list_for_user(session, user.id):
        if account.provider != "xunlei":
            continue
        try:
            stored = decrypt_cookie(account.cookie_ciphertext, key)
        except RuntimeError:
            continue
        if xunlei_subject(stored) == subject:
            matches.append(account)
    if not matches:
        return None
    return max(matches, key=lambda row: (row.updated_at, row.id))


def _has_account_history(session: Session, account_id: int) -> bool:
    for model in (Job, ShareLink, ShareStatSnapshot, DownloadTask, UploadTask):
        count = session.scalar(
            select(func.count())
            .select_from(model)
            .where(model.account_id == account_id)
        )
        if count:
            return True
    return False


def drop_empty_same_xunlei(
    session: Session, user: User, cookie: str, key: str, keep_id: int
) -> None:
    subject = xunlei_subject(cookie)
    if subject is None:
        return
    for account in list_for_user(session, user.id):
        if account.id == keep_id or account.provider != "xunlei":
            continue
        try:
            stored = decrypt_cookie(account.cookie_ciphertext, key)
        except RuntimeError:
            continue
        if xunlei_subject(stored) != subject or _has_account_history(
            session, account.id
        ):
            continue
        session.delete(account)


def ensure_slot(
    session: Session,
    user: User,
    now: datetime,
    provider: str,
    account: PanAccount | None,
) -> None:
    if (
        account is not None
        and account.provider == provider
        and account.status == "valid"
    ):
        return
    limit = account_limit(user, now)
    if limit is None:
        return
    if count_valid(session, user.id, provider) >= limit:
        name = {"baidu": "百度", "quark": "夸克"}.get(provider, "迅雷")
        if limit == 1:
            raise HTTPException(
                status_code=422, detail=f"免费用户只能绑定 1 个{name}账号"
            )
        raise HTTPException(status_code=422, detail=f"最多绑定 5 个{name}账号")


def verified_nickname(provider: str, cookie: str, client: httpx.Client) -> str:
    try:
        adapter = adapter_for(provider, client)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="网盘类型无效") from exc
    try:
        return adapter.verify_login(cookie)
    except ProviderClosed as exc:
        raise HTTPException(status_code=422, detail="暂未开放") from exc
    except LoginRejected as exc:
        name = {"baidu": "百度", "quark": "夸克"}.get(provider, "迅雷")
        raise HTTPException(status_code=422, detail=f"请重新扫码登录{name}") from exc


@router.get("")
def list_accounts(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> list[AccountOut]:
    rows = list_for_user(session, user.id)
    synced = _last_sync_map(session, [row.id for row in rows])
    return [to_account_out(row, synced.get(row.id)) for row in rows]


@router.post("", status_code=201)
def bind_account(
    body: AccountBindIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    now: datetime = Depends(now_utc),
) -> AccountOut:
    raise HTTPException(status_code=422, detail="请使用扫码登录")


@router.patch("/{account_id}")
def update_cookie(
    account_id: int,
    body: AccountCookieIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    now: datetime = Depends(now_utc),
) -> AccountOut:
    raise HTTPException(status_code=422, detail="请使用扫码登录")


def _login_out(item) -> BaiduLoginOut:
    return BaiduLoginOut(id=item.id, status=item.status, nickname=item.nickname)


@router.post("/baidu/login", status_code=201)
def start_baidu_login(
    body: BaiduLoginStartIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    now: datetime = Depends(now_utc),
) -> BaiduLoginOut:
    account = None
    if body.account_id is not None:
        account = owned_account(session, user, body.account_id)
    ensure_slot(session, user, now, "baidu", account)
    try:
        with pan_client(request) as client:
            started = start_qr(client)
    except QrLoginFailed as exc:
        raise HTTPException(
            status_code=502, detail="暂时无法打开百度登录，请稍后再试"
        ) from exc
    item = get_login_store(request).create(
        user_id=user.id,
        account_id=body.account_id,
        sign=started.sign,
        gid=started.gid,
        image=started.image,
        content_type=started.content_type,
    )
    return _login_out(item)


@router.get("/baidu/login/{session_id}/qrcode")
def baidu_login_qrcode(
    session_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> Response:
    item = get_login_store(request).get(session_id, user.id)
    if item is None or item.status == "expired":
        raise HTTPException(status_code=404, detail="登录已过期，请重新发起")
    return Response(content=item.image, media_type=item.content_type)


@router.get("/baidu/login/{session_id}")
def baidu_login_status(
    session_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> BaiduLoginOut:
    store = get_login_store(request)
    item = store.get(session_id, user.id)
    if item is None:
        raise HTTPException(status_code=404, detail="登录已过期，请重新发起")
    if item.status in {"ready", "expired"}:
        return _login_out(item)
    try:
        with pan_client(request) as client:
            polled = poll_qr(client, item.sign, item.gid)
            if polled.state == "ready" and polled.cookie:
                nickname = verified_nickname("baidu", polled.cookie, client)
                store.mark(
                    item.id, user.id, "ready", cookie=polled.cookie, nickname=nickname
                )
            elif polled.state == "scanned":
                store.mark(item.id, user.id, "scanned")
    except HTTPException:
        raise
    except QrLoginFailed as exc:
        raise HTTPException(
            status_code=502, detail="百度登录没有完成，请重新扫码"
        ) from exc
    current = store.get(session_id, user.id)
    if current is None:
        raise HTTPException(status_code=404, detail="登录已过期，请重新发起")
    return _login_out(current)


@router.delete("/baidu/login/{session_id}")
def cancel_baidu_login(
    session_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict:
    get_login_store(request).discard(session_id, user.id)
    return {"ok": True}


@router.post("/baidu/login/{session_id}/confirm")
def confirm_baidu_login(
    session_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    now: datetime = Depends(now_utc),
) -> AccountOut:
    store = get_login_store(request)
    item = store.get(session_id, user.id)
    if item is None or item.status == "expired":
        raise HTTPException(status_code=404, detail="登录已过期，请重新发起")
    if item.status != "ready" or not item.cookie or not item.nickname:
        raise HTTPException(status_code=422, detail="请先在手机上确认登录")
    account = None
    if item.account_id is not None:
        account = owned_account(session, user, item.account_id)
    ensure_slot(session, user, now, "baidu", account)
    if account is None:
        account = PanAccount(
            user_id=user.id,
            provider="baidu",
            nickname=item.nickname,
            cookie_ciphertext=encrypt_cookie(
                item.cookie, request.app.state.settings.cookie_fernet_key
            ),
            status="valid",
            created_at=now,
            updated_at=now,
        )
        account = add_account(session, account)
    else:
        account.nickname = item.nickname
        account.cookie_ciphertext = encrypt_cookie(
            item.cookie, request.app.state.settings.cookie_fernet_key
        )
        account.status = "valid"
        account.updated_at = now
    session.commit()
    session.refresh(account)
    store.discard(session_id, user.id)
    return to_account_out(account)


def owned_provider(
    session: Session, user: User, account_id: int, provider: str
) -> PanAccount:
    account = get_for_user(session, user.id, account_id)
    if account is None or account.provider != provider:
        raise HTTPException(status_code=404, detail="账号不存在")
    return account


@router.post("/quark/login", status_code=201)
def start_quark_login(
    body: BaiduLoginStartIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    now: datetime = Depends(now_utc),
) -> BaiduLoginOut:
    account = None
    if body.account_id is not None:
        account = owned_provider(session, user, body.account_id, "quark")
    ensure_slot(session, user, now, "quark", account)
    try:
        with pan_client(request) as client:
            started = start_quark_qr(client)
    except QuarkQrLoginFailed as exc:
        raise HTTPException(
            status_code=502, detail="暂时无法打开夸克登录，请稍后再试"
        ) from exc
    item = get_login_store(request).create(
        user_id=user.id,
        account_id=body.account_id,
        sign=started.sign,
        gid=started.gid,
        image=started.image,
        content_type=started.content_type,
    )
    return _login_out(item)


@router.get("/quark/login/{session_id}/qrcode")
def quark_login_qrcode(
    session_id: str, request: Request, user: User = Depends(get_current_user)
) -> Response:
    item = get_login_store(request).get(session_id, user.id)
    if item is None or item.status == "expired":
        raise HTTPException(status_code=404, detail="登录已过期，请重新发起")
    return Response(content=item.image, media_type=item.content_type)


@router.get("/quark/login/{session_id}")
def quark_login_status(
    session_id: str, request: Request, user: User = Depends(get_current_user)
) -> BaiduLoginOut:
    store = get_login_store(request)
    item = store.get(session_id, user.id)
    if item is None:
        raise HTTPException(status_code=404, detail="登录已过期，请重新发起")
    if item.status in {"ready", "expired"}:
        return _login_out(item)
    try:
        with pan_client(request) as client:
            polled = poll_quark_qr(client, item.sign, item.gid)
            if polled.state == "ready" and polled.cookie:
                checked = verified_nickname("quark", polled.cookie, client)
                store.mark(
                    item.id,
                    user.id,
                    "ready",
                    cookie=polled.cookie,
                    nickname=polled.nickname or checked,
                )
            elif polled.state == "scanned":
                store.mark(item.id, user.id, "scanned")
            elif polled.state == "expired":
                store.mark(item.id, user.id, "expired")
    except HTTPException:
        raise
    except QuarkQrLoginFailed as exc:
        raise HTTPException(
            status_code=502, detail="暂时无法打开夸克登录，请稍后再试"
        ) from exc
    current = store.get(session_id, user.id)
    if current is None:
        raise HTTPException(status_code=404, detail="登录已过期，请重新发起")
    return _login_out(current)


@router.delete("/quark/login/{session_id}")
def cancel_quark_login(
    session_id: str, request: Request, user: User = Depends(get_current_user)
) -> dict:
    get_login_store(request).discard(session_id, user.id)
    return {"ok": True}


@router.post("/quark/login/{session_id}/confirm")
def confirm_quark_login(
    session_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    now: datetime = Depends(now_utc),
) -> AccountOut:
    store = get_login_store(request)
    item = store.get(session_id, user.id)
    if item is None or item.status == "expired":
        raise HTTPException(status_code=404, detail="登录已过期，请重新发起")
    if item.status != "ready" or not item.cookie or not item.nickname:
        raise HTTPException(status_code=422, detail="请先在手机上确认登录")
    account = None
    if item.account_id is not None:
        account = owned_provider(session, user, item.account_id, "quark")
    ensure_slot(session, user, now, "quark", account)
    if account is None:
        account = PanAccount(
            user_id=user.id,
            provider="quark",
            nickname=item.nickname,
            cookie_ciphertext=encrypt_cookie(
                item.cookie, request.app.state.settings.cookie_fernet_key
            ),
            status="valid",
            created_at=now,
            updated_at=now,
        )
        account = add_account(session, account)
    else:
        account.nickname = item.nickname
        account.cookie_ciphertext = encrypt_cookie(
            item.cookie, request.app.state.settings.cookie_fernet_key
        )
        account.status = "valid"
        account.updated_at = now
    session.commit()
    session.refresh(account)
    store.discard(session_id, user.id)
    return to_account_out(account)


@router.post("/xunlei/login", status_code=201)
def start_xunlei_login(
    body: BaiduLoginStartIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    now: datetime = Depends(now_utc),
) -> BaiduLoginOut:
    account = None
    if body.account_id is not None:
        account = owned_provider(session, user, body.account_id, "xunlei")
    ensure_slot(session, user, now, "xunlei", account)
    try:
        with pan_client(request) as client:
            started = start_xunlei_qr(client)
    except XunleiQrLoginFailed as exc:
        raise HTTPException(
            status_code=502, detail="暂时无法打开迅雷登录，请稍后再试"
        ) from exc
    item = get_login_store(request).create(
        user_id=user.id,
        account_id=body.account_id,
        sign=started.sign,
        gid=started.gid,
        image=started.image,
        content_type=started.content_type,
    )
    return _login_out(item)


@router.get("/xunlei/login/{session_id}/qrcode")
def xunlei_login_qrcode(
    session_id: str, request: Request, user: User = Depends(get_current_user)
) -> Response:
    item = get_login_store(request).get(session_id, user.id)
    if item is None or item.status == "expired":
        raise HTTPException(status_code=404, detail="登录已过期，请重新发起")
    return Response(content=item.image, media_type=item.content_type)


@router.get("/xunlei/login/{session_id}")
def xunlei_login_status(
    session_id: str, request: Request, user: User = Depends(get_current_user)
) -> BaiduLoginOut:
    store = get_login_store(request)
    item = store.get(session_id, user.id)
    if item is None:
        raise HTTPException(status_code=404, detail="登录已过期，请重新发起")
    if item.status in {"ready", "expired"}:
        return _login_out(item)
    try:
        with pan_client(request) as client:
            polled = poll_xunlei_qr(client, item.sign, item.gid)
            if polled.state == "ready" and polled.cookie:
                checked = verified_nickname("xunlei", polled.cookie, client)
                store.mark(
                    item.id,
                    user.id,
                    "ready",
                    cookie=polled.cookie,
                    nickname=polled.nickname or checked,
                )
            elif polled.state == "scanned":
                store.mark(item.id, user.id, "scanned")
            elif polled.state == "expired":
                store.mark(item.id, user.id, "expired")
    except HTTPException:
        raise
    except XunleiQrLoginFailed as exc:
        raise HTTPException(
            status_code=502, detail="暂时无法打开迅雷登录，请稍后再试"
        ) from exc
    current = store.get(session_id, user.id)
    if current is None:
        raise HTTPException(status_code=404, detail="登录已过期，请重新发起")
    return _login_out(current)


@router.delete("/xunlei/login/{session_id}")
def cancel_xunlei_login(
    session_id: str, request: Request, user: User = Depends(get_current_user)
) -> dict:
    get_login_store(request).discard(session_id, user.id)
    return {"ok": True}


@router.post("/xunlei/login/{session_id}/confirm")
def confirm_xunlei_login(
    session_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    now: datetime = Depends(now_utc),
) -> AccountOut:
    store = get_login_store(request)
    item = store.get(session_id, user.id)
    if item is None or item.status == "expired":
        raise HTTPException(status_code=404, detail="登录已过期，请重新发起")
    if item.status != "ready" or not item.cookie or not item.nickname:
        raise HTTPException(status_code=422, detail="请先在手机上确认登录")
    account = None
    if item.account_id is not None:
        account = owned_provider(session, user, item.account_id, "xunlei")
    if account is None:
        account = same_xunlei_account(
            session, user, item.cookie, request.app.state.settings.cookie_fernet_key
        )
    ensure_slot(session, user, now, "xunlei", account)
    if account is None:
        account = PanAccount(
            user_id=user.id,
            provider="xunlei",
            nickname=item.nickname,
            cookie_ciphertext=encrypt_cookie(
                item.cookie, request.app.state.settings.cookie_fernet_key
            ),
            status="valid",
            created_at=now,
            updated_at=now,
        )
        account = add_account(session, account)
    else:
        account.nickname = item.nickname
        account.cookie_ciphertext = encrypt_cookie(
            item.cookie, request.app.state.settings.cookie_fernet_key
        )
        account.status = "valid"
        account.updated_at = now
    drop_empty_same_xunlei(
        session,
        user,
        item.cookie,
        request.app.state.settings.cookie_fernet_key,
        account.id,
    )
    session.commit()
    session.refresh(account)
    store.discard(session_id, user.id)
    return to_account_out(account)
