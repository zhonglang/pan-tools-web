from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import PanAccount, User


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


def test_pan_account_round_trip():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(email="user@example.com", password_hash="hash", role="user", plan="free")
        session.add(user)
        session.commit()
        session.add(
            PanAccount(
                user_id=user.id,
                provider="baidu",
                nickname="网盘昵称",
                cookie_ciphertext="ciphertext",
                status="valid",
            )
        )
        session.commit()
        saved = session.query(PanAccount).one()
        assert saved.user_id == user.id
        assert saved.provider == "baidu"
        assert saved.nickname == "网盘昵称"
        assert saved.cookie_ciphertext == "ciphertext"
        assert saved.status == "valid"
        assert saved.created_at is not None
        assert saved.updated_at is not None
