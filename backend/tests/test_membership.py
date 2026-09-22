from datetime import datetime, timezone

from app.membership import can_use_paid_features, effective_plan
from app.models import User


def _user(role: str, plan: str, expires: datetime | None) -> User:
    return User(
        email="user@example.com",
        password_hash="hash",
        role=role,
        plan=plan,
        plan_expires_at=expires,
        created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)


def test_paid_before_expiry():
    user = _user("user", "paid", datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert effective_plan(user, NOW) == "paid"
    assert can_use_paid_features(user, NOW) is True


def test_paid_after_expiry_is_free():
    user = _user("user", "paid", datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert effective_plan(user, NOW) == "free"
    assert can_use_paid_features(user, NOW) is False


def test_paid_without_expiry_is_free():
    user = _user("user", "paid", None)
    assert effective_plan(user, NOW) == "free"


def test_naive_expiry_is_treated_as_utc():
    user = _user("user", "paid", datetime(2026, 10, 1))
    assert effective_plan(user, NOW) == "paid"


def test_admin_can_use_paid_features_on_free_plan():
    user = _user("admin", "free", None)
    assert effective_plan(user, NOW) == "free"
    assert can_use_paid_features(user, NOW) is True
