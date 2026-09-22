from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import User


def test_user_round_trip():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    expires = datetime(2026, 10, 1, tzinfo=timezone.utc)
    with Session(engine) as session:
        session.add(
            User(
                email="user@example.com",
                password_hash="hash",
                role="user",
                plan="paid",
                plan_expires_at=expires,
            )
        )
        session.commit()
        saved = session.query(User).filter_by(email="user@example.com").one()
        assert saved.role == "user"
        assert saved.plan == "paid"
        assert saved.plan_expires_at is not None
