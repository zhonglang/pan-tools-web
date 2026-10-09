import httpx

from app.pans.baidu import DirEntry
from app.pans.errors import DuplicateName, LoginRejected, PathNotFound, TransferFailed

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

    def _params(self, extra: dict | None = None) -> dict:
        merged = dict(PARAMS)
        if extra:
            merged.update(extra)
        return merged

    def _payload(self, response: httpx.Response) -> dict:
        try:
            payload = response.json()
        except Exception as exc:
            raise TransferFailed() from exc
        if not isinstance(payload, dict):
            raise TransferFailed()
        if payload.get("status") == 200:
            return payload
        message = payload.get("message")
        text = message if isinstance(message, str) and message else "夸克请求失败"
        if "未登录" in text or payload.get("status") in {401, 403}:
            raise LoginRejected()
        if "同名" in text:
            raise DuplicateName()
        raise TransferFailed()

    def _get(self, path: str, cookie: str, params: dict) -> dict:
        try:
            response = self.client.get(
                f"{BASE}{path}",
                params=self._params(params),
                headers=self._headers(cookie),
                timeout=20,
            )
        except Exception as exc:
            raise TransferFailed() from exc
        return self._payload(response)

    def _post(self, path: str, cookie: str, body: dict) -> dict:
        try:
            response = self.client.post(
                f"{BASE}{path}",
                params=PARAMS,
                headers={**self._headers(cookie), "Content-Type": "application/json"},
                json=body,
                timeout=20,
            )
        except Exception as exc:
            raise TransferFailed() from exc
        return self._payload(response)

    def list_dir(self, cookie: str, directory: str) -> list[DirEntry]:
        parent = _fid(directory)
        rows: list[dict] = []
        page = 1
        while True:
            payload = self._get(
                "/file/sort",
                cookie,
                {"pdir_fid": parent, "_page": page, "_size": 100, "_fetch_total": 1},
            )
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            batch = data.get("list") or []
            if not isinstance(batch, list):
                raise PathNotFound()
            rows.extend(item for item in batch if isinstance(item, dict))
            if len(batch) < 100:
                break
            page += 1
        entries: list[DirEntry] = []
        for item in rows:
            fid = item.get("fid")
            name = item.get("file_name")
            if not isinstance(fid, str) or not fid or not isinstance(name, str):
                continue
            size = item.get("size")
            modified = item.get("updated_at")
            if isinstance(modified, int) and modified >= 10**12:
                modified = modified // 1000
            entries.append(
                DirEntry(
                    name=name,
                    path=f"/{fid}",
                    is_dir=item.get("file_type") == 0,
                    size=size if isinstance(size, int) else None,
                    modified_at=modified if isinstance(modified, int) else None,
                )
            )
        return entries

    def create_dir(self, cookie: str, directory: str, name: str) -> DirEntry:
        payload = self._post(
            "/file",
            cookie,
            {"pdir_fid": _fid(directory), "file_name": name, "dir_init_lock": False},
        )
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        fid = data.get("fid")
        if not isinstance(fid, str) or not fid:
            raise TransferFailed()
        return DirEntry(name=name, path=f"/{fid}", is_dir=True)

    def rename(self, cookie: str, path: str, new_name: str) -> None:
        self._post("/file/rename", cookie, {"fid": _fid(path), "file_name": new_name})

    def delete(self, cookie: str, path: str) -> None:
        self._post("/file/delete", cookie, {"action_type": 2, "filelist": [_fid(path)], "exclude_fids": []})


def _fid(directory: str) -> str:
    cleaned = directory.strip().rstrip("/")
    if cleaned in {"", "/"}:
        return "0"
    return cleaned.rsplit("/", 1)[-1]
