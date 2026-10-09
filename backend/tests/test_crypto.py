import pytest

from app.core.crypto import decrypt_cookie, encrypt_cookie

KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
COOKIE = "BDUSS=super-secret-cookie-value"


def test_encrypt_round_trip_hides_plaintext():
    ciphertext = encrypt_cookie(COOKIE, KEY)
    assert COOKIE not in ciphertext
    assert decrypt_cookie(ciphertext, KEY) == COOKIE


def test_invalid_key_is_rejected():
    with pytest.raises(RuntimeError, match="COOKIE_FERNET_KEY 无效"):
        encrypt_cookie(COOKIE, "not-a-fernet-key")


def test_tampered_ciphertext_is_rejected():
    ciphertext = encrypt_cookie(COOKIE, KEY)
    with pytest.raises(RuntimeError, match="Cookie 无法解密"):
        decrypt_cookie(ciphertext[:-2] + "aa", KEY)
