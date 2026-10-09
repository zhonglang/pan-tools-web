from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.crud.usage import get_for_day, get_or_create
from app.services.membership import as_utc, can_use_paid_features, effective_plan
from app.models import User

TRANSFER_LIMIT = 100
SHANGHAI = ZoneInfo("Asia/Shanghai")


class QuotaRejected(Exception):
    def __init__(self, remaining: int) -> None:
        self.remaining = remaining
        super().__init__(f"今日还可转存 {remaining} 条")


class PaidRequired(Exception):
    def __init__(self) -> None:
        super().__init__("该功能仅对付费会员开放")


def shanghai_today(now: datetime) -> date:
    current = as_utc(now)
    if current is None:
        raise ValueError("now is required")
    return current.astimezone(SHANGHAI).date()


def reserve_transfers(session: Session, user: User, now: datetime, count: int) -> None:
    if count < 1:
        raise ValueError("count must be positive")
    if user.role == "admin":
        return
    day = shanghai_today(now)
    usage = get_for_day(session, user.id, day)
    used = 0 if usage is None else usage.transfer_count
    if effective_plan(user, now) == "free":
        remaining = max(TRANSFER_LIMIT - used, 0)
        if used + count > TRANSFER_LIMIT:
            raise QuotaRejected(remaining)
    usage = get_or_create(session, user.id, day)
    usage.transfer_count += count


def reserve_shares(session: Session, user: User, now: datetime, count: int) -> None:
    if count < 1:
        raise ValueError("count must be positive")
    if not can_use_paid_features(user, now):
        raise PaidRequired()
    if user.role == "admin":
        return
    day = shanghai_today(now)
    usage = get_or_create(session, user.id, day)
    usage.share_count += count
