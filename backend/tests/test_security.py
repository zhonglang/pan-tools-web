from app.security import hash_password, verify_password


def test_hash_verifies_same_password():
    hashed = hash_password("admin-pass-123")
    assert hashed != "admin-pass-123"
    assert verify_password("admin-pass-123", hashed) is True


def test_hash_rejects_wrong_password():
    hashed = hash_password("admin-pass-123")
    assert verify_password("other-pass-123", hashed) is False
