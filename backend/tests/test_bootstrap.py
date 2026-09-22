from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.bootstrap import ensure_admin
from app.config import Settings
from app.db import Base
from app.models import User


def test_ensure_admin_raises_when_admin_email_taken_by_non_admin():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings(
        jwt_secret="test-secret-key-at-least-32-bytes-long",
        admin_email="admin@example.com",
        admin_password="admin-pass-123",
        cookie_fernet_key="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    with Session(engine) as session:
        session.add(
            User(
                email="admin@example.com",
                password_hash="hash",
                role="user",
                plan="free",
                plan_expires_at=None,
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        with pytest.raises(RuntimeError, match="无法创建管理员：邮箱 admin@example.com 已被占用"):
            ensure_admin(session, settings)


def test_startup_creates_admin(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "admin-pass-123"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "admin"
    assert body["paid_features"] is True
    assert "password" not in body
