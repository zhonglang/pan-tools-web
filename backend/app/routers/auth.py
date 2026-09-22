from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.deps import get_db, now_utc
from app.membership import can_use_paid_features, effective_plan
from app.models import User
from app.schemas import RegisterIn, UserOut
from app.security import create_access_token, hash_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def to_user_out(user: User, now: datetime) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        role=user.role,
        plan=user.plan,
        effective_plan=effective_plan(user, now),
        plan_expires_at=user.plan_expires_at,
        paid_features=can_use_paid_features(user, now),
    )


def set_session_cookie(response: Response, user: User, settings: Settings) -> None:
    token = create_access_token(user.id, settings.jwt_secret, settings.jwt_ttl_seconds)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.jwt_ttl_seconds,
        path="/",
    )


@router.post("/register", response_model=UserOut, status_code=201)
def register(
    payload: RegisterIn,
    response: Response,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    email = payload.email.lower()
    exists = session.scalar(select(User).where(func.lower(User.email) == email))
    if exists is not None:
        raise HTTPException(status_code=409, detail="邮箱已注册")
    try:
        password_hash = hash_password(payload.password)
    except ValueError:
        raise HTTPException(status_code=422, detail="密码无效")
    user = User(
        email=email,
        password_hash=password_hash,
        role="user",
        plan="free",
        plan_expires_at=None,
        created_at=datetime.now(timezone.utc),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    set_session_cookie(response, user, settings)
    return to_user_out(user, now_utc())
