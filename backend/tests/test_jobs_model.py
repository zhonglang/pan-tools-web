from datetime import date, datetime, timezone

from sqlalchemy import select

from app.models import DailyUsage, Job, JobItem, User


def test_job_item_defaults_and_usage_day(client):
    with client.app.state.session_factory() as session:
        user = User(email="quota@example.com", password_hash="x")
        session.add(user)
        session.flush()
        job = Job(user_id=user.id, account_id=1, type="transfer", directory="/来自转存", status="pending")
        session.add(job)
        session.flush()
        session.add(JobItem(job_id=job.id, input_text="https://pan.baidu.com/s/1abc", status="pending"))
        session.add(DailyUsage(user_id=user.id, usage_date=date(2026, 9, 22), transfer_count=3, share_count=0))
        session.commit()
        stored = session.scalars(select(JobItem)).one()
        usage = session.scalars(select(DailyUsage)).one()
        assert stored.attempts == 0
        assert stored.error is None
        assert stored.result is None
        assert usage.transfer_count == 3
        assert job.created_at.tzinfo is not None or isinstance(job.created_at, datetime)
