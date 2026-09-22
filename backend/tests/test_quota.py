from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import DailyUsage, User
from app.quota import QuotaRejected, reserve_transfers, shanghai_today

SHANGHAI_NOON = datetime(2026, 9, 22, 4, 0, tzinfo=timezone.utc)  # 上海 12:00


def add_user(session, email, plan="free", expires=None, role="user"):
    user = User(email=email, password_hash="x", plan=plan, plan_expires_at=expires, role=role)
    session.add(user)
    session.flush()
    return user


def test_shanghai_day_crosses_utc_midnight():
    assert shanghai_today(datetime(2026, 9, 21, 16, 30, tzinfo=timezone.utc)) == shanghai_today(SHANGHAI_NOON)


def test_free_user_over_limit_keeps_usage(client):
    with client.app.state.session_factory() as session:
        user = add_user(session, "free@example.com")
        session.add(DailyUsage(user_id=user.id, usage_date=shanghai_today(SHANGHAI_NOON), transfer_count=100, share_count=0))
        session.commit()
        user_id = user.id
    with client.app.state.session_factory() as session:
        user = session.get(User, user_id)
        with pytest.raises(QuotaRejected) as caught:
            reserve_transfers(session, user, SHANGHAI_NOON, 1)
        assert caught.value.remaining == 0
        session.commit()
        usage = session.scalars(select(DailyUsage)).one()
        assert usage.transfer_count == 100


def test_paid_user_can_exceed_and_admin_is_not_counted(client):
    later = SHANGHAI_NOON + timedelta(days=2)
    with client.app.state.session_factory() as session:
        paid = add_user(session, "paid@example.com", plan="paid", expires=later)
        admin = add_user(session, "admin-quota@example.com", role="admin")
        reserve_transfers(session, paid, SHANGHAI_NOON, 101)
        reserve_transfers(session, admin, SHANGHAI_NOON, 50)
        session.commit()
        rows = session.scalars(select(DailyUsage)).all()
        assert len(rows) == 1
        assert rows[0].user_id == paid.id
        assert rows[0].transfer_count == 101


def test_expired_paid_user_is_free(client):
    expired = SHANGHAI_NOON - timedelta(minutes=1)
    with client.app.state.session_factory() as session:
        user = add_user(session, "expired@example.com", plan="paid", expires=expired)
        session.add(DailyUsage(user_id=user.id, usage_date=shanghai_today(SHANGHAI_NOON), transfer_count=100, share_count=0))
        session.commit()
        user_id = user.id
    with client.app.state.session_factory() as session:
        user = session.get(User, user_id)
        with pytest.raises(QuotaRejected) as caught:
            reserve_transfers(session, user, SHANGHAI_NOON, 1)
        assert caught.value.remaining == 0
