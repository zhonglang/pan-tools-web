from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.routes.auth import to_user_out
from app.core.deps import get_db, now_utc, require_admin
from app.crud.users import get as get_user
from app.crud.users import list_all
from app.models import User
from app.schemas import PlanUpdateIn, UserOut
from app.services.membership import as_utc

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
def list_users(session: Session = Depends(get_db), _: User = Depends(require_admin)):
    now = now_utc()
    users = list_all(session)
    return [to_user_out(user, now) for user in users]


@router.patch("/users/{user_id}", response_model=UserOut)
def update_plan(
    user_id: int,
    payload: PlanUpdateIn,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    if payload.plan not in {"free", "paid"}:
        raise HTTPException(status_code=422, detail="等级只能是 free 或 paid")
    user = get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if payload.plan == "paid":
        expires = as_utc(payload.plan_expires_at)
        if expires is None:
            raise HTTPException(status_code=422, detail="付费等级必须填写到期时间")
        user.plan = "paid"
        user.plan_expires_at = expires
    else:
        user.plan = "free"
        user.plan_expires_at = None
    session.commit()
    session.refresh(user)
    return to_user_out(user, now_utc())
