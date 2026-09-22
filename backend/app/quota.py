from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.membership import as_utc, effective_plan
from app.models import DailyUsage, User

TRANSFER_LIMIT = 100
SHANGHAI = ZoneInfo("Asia/Shanghai")


class QuotaRejected(Exception):
    def __init__(self, remaining: int) -> None:
        self.remaining = remaining
        super().__init__(f"今日还可转存 {remaining} 条")


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
    usage = session.scalar(
        select(DailyUsage).where(DailyUsage.user_id == user.id, DailyUsage.usage_date == day)
    )
    used = 0 if usage is None else usage.transfer_count
    if effective_plan(user, now) == "free":
        remaining = max(TRANSFER_LIMIT - used, 0)
        if used + count > TRANSFER_LIMIT:
            raise QuotaRejected(remaining)
    if usage is None:
        usage = DailyUsage(user_id=user.id, usage_date=day, transfer_count=0, share_count=0)
        session.add(usage)
    usage.transfer_count += count
