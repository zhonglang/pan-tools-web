from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DailyUsage


def get_for_day(session: Session, user_id: int, day: date) -> DailyUsage | None:
    return session.scalar(select(DailyUsage).where(DailyUsage.user_id == user_id, DailyUsage.usage_date == day))


def get_or_create(session: Session, user_id: int, day: date) -> DailyUsage:
    usage = get_for_day(session, user_id, day)
    if usage is None:
        usage = DailyUsage(user_id=user_id, usage_date=day, transfer_count=0, share_count=0)
        session.add(usage)
    return usage
