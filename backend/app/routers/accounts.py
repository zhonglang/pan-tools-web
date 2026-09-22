from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.crypto import encrypt_cookie
from app.deps import get_current_user, get_db, now_utc
from app.membership import baidu_account_limit
from app.models import PanAccount, User
from app.pans import LoginRejected, ProviderClosed, adapter_for
from app.schemas import AccountBindIn, AccountCookieIn, AccountOut

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def get_pan_http_client(request: Request) -> httpx.Client:
    client = getattr(request.app.state, "pan_http_client", None)
    if client is None:
        client = httpx.Client()
        request.app.state.pan_http_client = client
    return client


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
    count = session.scalar(
        select(func.count())
        .select_from(PanAccount)
        .where(
            PanAccount.user_id == user.id,
            PanAccount.provider == "baidu",
            PanAccount.status == "valid",
        )
    )
    if count is not None and count >= limit:
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
    rows = session.scalars(select(PanAccount).where(PanAccount.user_id == user.id).order_by(PanAccount.id)).all()
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
    session.add(account)
    session.commit()
    session.refresh(account)
    return to_account_out(account)


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
    account = session.scalar(
        select(PanAccount).where(PanAccount.id == account_id, PanAccount.user_id == user.id)
    )
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
