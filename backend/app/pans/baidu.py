import httpx

from app.pans.errors import LoginRejected

BAIDU_UINFO = "https://pan.baidu.com/rest/2.0/xpan/nas"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


class BaiduAdapter:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def verify_login(self, cookie: str) -> str:
        try:
            response = self.client.get(
                BAIDU_UINFO,
                params={"method": "uinfo"},
                headers={"Cookie": cookie, "User-Agent": USER_AGENT},
                timeout=10,
                follow_redirects=False,
            )
            payload = response.json() if response.status_code == 200 else None
        except Exception as exc:
            raise LoginRejected() from exc
        if not isinstance(payload, dict) or payload.get("errno") != 0:
            raise LoginRejected()
        for key in ("netdisk_name", "baidu_name"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        raise LoginRejected()
