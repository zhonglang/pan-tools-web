import secrets
import threading
import time
from dataclasses import dataclass


@dataclass
class LoginSession:
    id: str
    user_id: int
    account_id: int | None
    sign: str
    gid: str
    image: bytes
    content_type: str
    status: str
    cookie: str | None
    nickname: str | None
    created_at: float


class LoginSessionStore:
    def __init__(self, ttl_seconds: int = 180) -> None:
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, LoginSession] = {}
        self._lock = threading.Lock()

    def create(
        self,
        user_id: int,
        account_id: int | None,
        sign: str,
        gid: str,
        image: bytes,
        content_type: str,
    ) -> LoginSession:
        item = LoginSession(
            id=secrets.token_urlsafe(18),
            user_id=user_id,
            account_id=account_id,
            sign=sign,
            gid=gid,
            image=image,
            content_type=content_type,
            status="waiting",
            cookie=None,
            nickname=None,
            created_at=time.time(),
        )
        with self._lock:
            self._items[item.id] = item
        return item

    def get(self, session_id: str, user_id: int) -> LoginSession | None:
        with self._lock:
            item = self._items.get(session_id)
            if item is None or item.user_id != user_id:
                return None
            if time.time() - item.created_at > self.ttl_seconds:
                item.status = "expired"
                item.cookie = None
            return item

    def mark(
        self,
        session_id: str,
        user_id: int,
        status: str,
        cookie: str | None = None,
        nickname: str | None = None,
    ) -> None:
        with self._lock:
            item = self._items.get(session_id)
            if item is None or item.user_id != user_id or item.status == "expired":
                return
            item.status = status
            if cookie is not None:
                item.cookie = cookie
            if nickname is not None:
                item.nickname = nickname

    def discard(self, session_id: str, user_id: int) -> None:
        with self._lock:
            item = self._items.get(session_id)
            if item is not None and item.user_id == user_id:
                item.cookie = None
                del self._items[session_id]
