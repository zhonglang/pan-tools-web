from contextlib import contextmanager
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.crypto import encrypt_cookie
from app.core.deps import get_current_user, get_db, now_utc
from app.crud.accounts import add as add_account
from app.crud.accounts import count_valid_baidu, get_for_user, list_for_user
from app.models import PanAccount, User
from app.services.baidu_login_sessions import LoginSessionStore
from app.services.membership import baidu_account_limit
from app.pans import LoginRejected, ProviderClosed, adapter_for
from app.pans.baidu_login import QrLoginFailed, poll_qr, start_qr
from app.schemas import AccountBindIn, AccountCookieIn, AccountOut, BaiduLoginOut, BaiduLoginStartIn

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


def to_account_out(account: PanAccount) -> AccountOut:
    return AccountOut(
        id=account.id,
        provider=account.provider,
        nickname=account.nickname,
        status=account.status,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


def ensure_baidu_slot(session: Session, user: User, now: datetime, account: PanAccount | None) -> None:
    if account is not None and account.provider == "baidu" and account.status == "valid":
        return
    limit = baidu_account_limit(user, now)
    count = count_valid_baidu(session, user.id)
    if count >= limit:
        if limit == 1:
            raise HTTPException(status_code=422, detail="免费用户只能绑定 1 个百度账号")
        raise HTTPException(status_code=422, detail="最多绑定 5 个百度账号")


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
        raise HTTPException(status_code=422, detail="请重新登录百度后再粘贴 Cookie") from exc


def clean_cookie(cookie: str) -> str:
    value = cookie.strip()
    if not value:
        raise HTTPException(status_code=422, detail="Cookie 不能为空")
    return value


@router.get("")
def list_accounts(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> list[AccountOut]:
    rows = list_for_user(session, user.id)
    return [to_account_out(row) for row in rows]


@router.post("", status_code=201)
def bind_account(
    body: AccountBindIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    now: datetime = Depends(now_utc),
) -> AccountOut:
    cookie = clean_cookie(body.cookie)
    if body.provider not in {"baidu", "quark", "xunlei"}:
        raise HTTPException(status_code=422, detail="网盘类型无效")
    if body.provider == "baidu":
        ensure_baidu_slot(session, user, now, None)
    nickname = verified_nickname(body.provider, cookie, get_pan_http_client(request))
    account = PanAccount(
        user_id=user.id,
        provider=body.provider,
        nickname=nickname,
        cookie_ciphertext=encrypt_cookie(cookie, request.app.state.settings.cookie_fernet_key),
        status="valid",
        created_at=now,
        updated_at=now,
    )
    return to_account_out(add_account(session, account))


@router.patch("/{account_id}")
def update_cookie(
    account_id: int,
    body: AccountCookieIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    now: datetime = Depends(now_utc),
) -> AccountOut:
    cookie = clean_cookie(body.cookie)
    account = get_for_user(session, user.id, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    if account.provider == "baidu":
        ensure_baidu_slot(session, user, now, account)
    nickname = verified_nickname(account.provider, cookie, get_pan_http_client(request))
    account.nickname = nickname
    account.cookie_ciphertext = encrypt_cookie(cookie, request.app.state.settings.cookie_fernet_key)
    account.status = "valid"
    account.updated_at = now
    session.commit()
    session.refresh(account)
    return to_account_out(account)


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
    ensure_baidu_slot(session, user, now, account)
    try:
        with pan_client(request) as client:
            started = start_qr(client)
    except QrLoginFailed as exc:
        raise HTTPException(status_code=502, detail="暂时无法打开百度登录，请稍后再试") from exc
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
                store.mark(item.id, user.id, "ready", cookie=polled.cookie, nickname=nickname)
            elif polled.state == "scanned":
                store.mark(item.id, user.id, "scanned")
    except HTTPException:
        raise
    except QrLoginFailed as exc:
        raise HTTPException(status_code=502, detail="百度登录没有完成，请重新扫码") from exc
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
    ensure_baidu_slot(session, user, now, account)
    if account is None:
        account = PanAccount(
            user_id=user.id,
            provider="baidu",
            nickname=item.nickname,
            cookie_ciphertext=encrypt_cookie(item.cookie, request.app.state.settings.cookie_fernet_key),
            status="valid",
            created_at=now,
            updated_at=now,
        )
        account = add_account(session, account)
    else:
        account.nickname = item.nickname
        account.cookie_ciphertext = encrypt_cookie(item.cookie, request.app.state.settings.cookie_fernet_key)
        account.status = "valid"
        account.updated_at = now
    session.commit()
    session.refresh(account)
    store.discard(session_id, user.id)
    return to_account_out(account)
