from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.deps import get_current_user, get_db, now_utc
from app.core.security import create_access_token, hash_password, verify_password
from app.crud.users import add as add_user
from app.crud.users import get_by_email
from app.models import User
from app.schemas import LoginIn, RegisterIn, UserOut
from app.services.membership import can_use_paid_features, effective_plan

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
    if get_by_email(session, email) is not None:
        raise HTTPException(status_code=409, detail="邮箱已注册")
    try:
        password_hash = hash_password(payload.password)
    except ValueError:
        raise HTTPException(status_code=422, detail="密码无效")
    user = add_user(
        session,
        User(
            email=email,
            password_hash=password_hash,
            role="user",
            plan="free",
            plan_expires_at=None,
            created_at=datetime.now(timezone.utc),
        ),
    )
    set_session_cookie(response, user, settings)
    return to_user_out(user, now_utc())


@router.post("/login", response_model=UserOut)
def login(
    payload: LoginIn,
    response: Response,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    email = payload.email.lower()
    user = get_by_email(session, email)
    password_ok = False
    if user is not None:
        try:
            password_ok = verify_password(payload.password, user.password_hash)
        except ValueError:
            password_ok = False
    if user is None or not password_ok:
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    set_session_cookie(response, user, settings)
    return to_user_out(user, now_utc())


@router.post("/logout")
def logout(response: Response, settings: Settings = Depends(get_settings)):
    response.delete_cookie(
        "access_token",
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return to_user_out(user, now_utc())
