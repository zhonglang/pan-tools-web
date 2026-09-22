from datetime import datetime, timedelta, timezone

from app.membership import baidu_account_limit, can_use_paid_features, effective_plan
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


def test_free_user_can_bind_one_baidu_account():
    user = _user("user", "free", None)
    assert baidu_account_limit(user, datetime.now(timezone.utc)) == 1


def test_paid_user_can_bind_five_baidu_accounts():
    user = _user("user", "paid", datetime.now(timezone.utc) + timedelta(days=1))
    assert baidu_account_limit(user, datetime.now(timezone.utc)) == 5


def test_expired_paid_user_can_bind_one_baidu_account():
    user = _user("user", "paid", datetime.now(timezone.utc) - timedelta(days=1))
    assert baidu_account_limit(user, datetime.now(timezone.utc)) == 1


def test_admin_can_bind_five_baidu_accounts():
    user = _user("admin", "free", None)
    assert baidu_account_limit(user, datetime.now(timezone.utc)) == 5
