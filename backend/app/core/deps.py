from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.crud.users import get as get_user
from app.models import User
from app.core.security import decode_access_token


def get_db(request: Request):
    session: Session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_current_user(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        user_id = decode_access_token(token, settings.jwt_secret)
    except Exception:
        raise HTTPException(status_code=401, detail="未登录")
    user = get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
