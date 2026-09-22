from datetime import datetime, timedelta, timezone

import bcrypt
import jwt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(user_id: int, secret: str, ttl_seconds: int, now: datetime | None = None) -> str:
    issued = now or datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "exp": issued + timedelta(seconds=ttl_seconds)}
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, secret: str, now: datetime | None = None) -> int:
    payload = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        options={"verify_exp": now is None},
    )
    if now is not None:
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        if exp <= now:
            raise jwt.ExpiredSignatureError("token expired")
    return int(payload["sub"])
