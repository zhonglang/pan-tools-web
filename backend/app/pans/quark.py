import httpx

from app.pans.errors import LoginRejected

BASE = "https://drive-pc.quark.cn/1/clouddrive"
PARAMS = {"pr": "ucpro", "fr": "pc"}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


class QuarkAdapter:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def _headers(self, cookie: str) -> dict[str, str]:
        return {"Cookie": cookie, "User-Agent": USER_AGENT}

    def verify_login(self, cookie: str) -> str:
        try:
            response = self.client.get(
                f"{BASE}/member",
                params=PARAMS,
                headers=self._headers(cookie),
                timeout=10,
            )
            payload = response.json()
        except Exception as exc:
            raise LoginRejected() from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        nickname = data.get("nickname") if isinstance(data, dict) else None
        if not isinstance(payload, dict) or payload.get("status") != 200 or not isinstance(nickname, str) or not nickname.strip():
            raise LoginRejected()
        return nickname.strip()
