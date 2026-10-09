from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_verifies_same_password():
    hashed = hash_password("admin-pass-123")
    assert hashed != "admin-pass-123"
    assert verify_password("admin-pass-123", hashed) is True


def test_hash_rejects_wrong_password():
    hashed = hash_password("admin-pass-123")
    assert verify_password("other-pass-123", hashed) is False


def test_token_contains_user_id():
    now = datetime(2026, 9, 22, tzinfo=timezone.utc)
    token = create_access_token(7, "secret", 3600, now=now)
    assert decode_access_token(token, "secret", now=now) == 7


def test_expired_token_is_rejected():
    now = datetime(2026, 9, 22, tzinfo=timezone.utc)
    token = create_access_token(7, "secret", 3600, now=now)
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, "secret", now=now + timedelta(seconds=3601))
