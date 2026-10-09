from datetime import datetime, timezone

from app.models import User


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def effective_plan(user: User, now: datetime) -> str:
    expires = as_utc(user.plan_expires_at)
    current = as_utc(now)
    if user.plan == "paid" and expires is not None and current is not None and expires > current:
        return "paid"
    return "free"


def can_use_paid_features(user: User, now: datetime) -> bool:
    return user.role == "admin" or effective_plan(user, now) == "paid"


def account_limit(user: User, now: datetime) -> int | None:
    if user.role == "admin":
        return None
    if can_use_paid_features(user, now):
        return 5
    return 1


def baidu_account_limit(user: User, now: datetime) -> int | None:
    return account_limit(user, now)
