from cryptography.fernet import Fernet, InvalidToken


def _fernet(key: str) -> Fernet:
    try:
        return Fernet(key.encode())
    except Exception as exc:
        raise RuntimeError("COOKIE_FERNET_KEY 无效") from exc


def encrypt_cookie(cookie: str, key: str) -> str:
    return _fernet(key).encrypt(cookie.encode()).decode()


def decrypt_cookie(ciphertext: str, key: str) -> str:
    try:
        return _fernet(key).decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Cookie 无法解密") from exc
