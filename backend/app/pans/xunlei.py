import hashlib
import json
import time
from collections.abc import Callable
from datetime import datetime
from urllib.parse import urlparse

import httpx

from app.pans.baidu import DirEntry, DownloadStream
from app.pans.errors import DuplicateName, InvalidLink, LoginRejected, RateLimited, TransferFailed, WrongPassword

API = "https://api-pan.xunlei.com/drive/v1"
AUTH = "https://xluser-ssl.xunlei.com/v1"
CLIENT_ID = "Xp6vsxz_7IYVw2BB"
CLIENT_SECRET = "Xp6vsy4tN9toTVdMSpomVdXpRmES"
CLIENT_VERSION = "8.31.0.9726"
# Web login client. Drive file calls reject tokens issued to it.
LOGIN_CLIENT_ID = "XW5SkOhLDjnOZP7J"
LOGIN_USER_AGENT = "Mozilla/5.0"
PACKAGE_NAME = "com.xunlei.downloadprovider"
USER_AGENT = (
    "ANDROID-com.xunlei.downloadprovider/8.31.0.9726 "
    "netWorkType/WIFI appid/40 deviceName/pan-tools deviceModel/pan-tools "
    "OSVersion/13 protocolVersion/301 platformVersion/10 sdkVersion/512000"
)
ALGORITHMS = (
    "9uJNVj/wLmdwKrJaVj/omlQ",
    "Oz64Lp0GigmChHMf/6TNfxx7O9PyopcczMsnf",
    "Eb+L7Ce+Ej48u",
    "jKY0",
    "ASr0zCl6v8W4aidjPK5KHd1Lq3t+vBFf41dqv5+fnOd",
    "wQlozdg6r1qxh0eRmt3QgNXOvSZO6q/GXK",
    "gmirk+ciAvIgA/cxUUCema47jr/YToixTT+Q6O",
    "5IiCoM9B1/788ntB",
    "P07JH0h6qoM6TSUAK2aL9T5s2QBVeY9JWvalf",
    "+oK0AN",
)
_TOKEN_ERRORS = {10, 16, 4121, 4122}
_PENDING = {"authorization_pending", "slow_down"}
_EXPIRED = {"expired_token", "access_denied"}


class XunleiAdapter:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.warmed: str | None = None

    def prepare(self, cookie: str) -> str:
        credential = self._live(_loads(cookie))
        return self._remember(credential)

    def verify_login(self, cookie: str) -> str:
        try:
            credential = self._live(_loads(cookie), action="GET:/v1/user/me")
            payload = self._send("GET", f"{AUTH}/user/me", credential, action="GET:/v1/user/me")
        except TransferFailed as exc:
            raise LoginRejected() from exc
        for key in ("name", "username", "nickname"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return "迅雷用户"

    def list_dir(self, cookie: str, directory: str) -> list[DirEntry]:
        credential = self._live(_loads(cookie))
        parent = _fid(directory)
        entries: list[DirEntry] = []
        page = ""
        for _ in range(100):
            payload = self._send(
                "GET",
                f"{API}/files",
                credential,
                params={
                    "parent_id": parent,
                    "page_token": page,
                    "limit": "100",
                    "with_audit": "true",
                    "filters": '{"phase":{"eq":"PHASE_TYPE_COMPLETE"},"trashed":{"eq":false}}',
                },
            )
            files = payload.get("files") or []
            if not isinstance(files, list):
                raise TransferFailed()
            for item in files:
                if isinstance(item, dict):
                    entries.append(_entry(item))
            page = payload.get("next_page_token") if isinstance(payload.get("next_page_token"), str) else ""
            if not page:
                return entries
        raise TransferFailed()

    def create_dir(self, cookie: str, directory: str, name: str) -> DirEntry:
        credential = self._live(_loads(cookie))
        payload = self._send(
            "POST",
            f"{API}/files",
            credential,
            body={"kind": "drive#folder", "name": name, "parent_id": _fid(directory)},
        )
        file = payload.get("file") if isinstance(payload.get("file"), dict) else payload
        fid = file.get("id") if isinstance(file, dict) else None
        if not isinstance(fid, str) or not fid:
            raise TransferFailed()
        return DirEntry(name=name, path=f"/{fid}", is_dir=True)

    def rename(self, cookie: str, path: str, new_name: str) -> None:
        credential = self._live(_loads(cookie))
        self._send("PATCH", f"{API}/files/{_fid(path)}", credential, body={"name": new_name})

    def delete(self, cookie: str, path: str) -> None:
        credential = self._live(_loads(cookie))
        self._send("PATCH", f"{API}/files/{_fid(path)}/trash", credential, body={})

    def copy(self, cookie: str, path: str, dest: str, new_name: str) -> None:
        existing = self.list_dir(cookie, dest)
        if any(entry.name == new_name for entry in existing):
            raise DuplicateName()
        before = {entry.path for entry in existing}
        credential = self._live(_loads(cookie))
        self._send(
            "POST",
            f"{API}/files/copy",
            credential,
            body={"file_ids": [_fid(path)], "to": {"parent_id": _fid(dest)}},
            action="POST:/drive/v1/files/copy",
        )
        after = self.list_dir(cookie, dest)
        newcomers = [entry for entry in after if entry.path not in before]
        if not newcomers:
            raise TransferFailed()
        item = newcomers[0]
        if item.name != new_name:
            self.rename(cookie, item.path, new_name)

    def transfer_share(
        self,
        cookie: str,
        surl: str,
        password: str | None,
        directory: str,
        *,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        credential = self._live(_loads(cookie))
        share_id = _share_id(surl)
        detail = self._send(
            "GET",
            f"{API}/share",
            credential,
            params={"share_id": share_id, "pass_code": password or "", "limit": "100"},
            invalid=True,
        )
        token = detail.get("pass_code_token")
        files = detail.get("files") or []
        if not isinstance(token, str) or not token or not isinstance(files, list):
            raise InvalidLink()
        file_ids = [item.get("id") for item in files if isinstance(item, dict) and isinstance(item.get("id"), str)]
        if not file_ids:
            raise InvalidLink()
        self._send(
            "POST",
            f"{API}/share/restore",
            credential,
            body={
                "parent_id": _fid(directory),
                "share_id": share_id,
                "pass_code_token": token,
                "ancestor_ids": [],
                "file_ids": file_ids,
                "specify_parent_id": True,
            },
        )

    def open_download(self, cookie: str, path: str):
        credential = self._live(_loads(cookie))
        payload = self._send("GET", f"{API}/files/{_fid(path)}", credential)
        url = payload.get("web_content_link")
        if not isinstance(url, str) or not url:
            raise TransferFailed()
        headers = self._headers(credential)
        try:
            response = self.client.get(url, headers={"User-Agent": headers["User-Agent"]}, timeout=30)
        except Exception as exc:
            raise TransferFailed() from exc
        if response.status_code != 200:
            raise TransferFailed()
        length = response.headers.get("content-length")
        size = int(length) if isinstance(length, str) and length.isdecimal() else len(response.content)

        def chunks():
            yield response.content

        return DownloadStream(chunks(), size)

    def list_share_records(self, cookie: str) -> list[dict]:
        credential = self._live(_loads(cookie))
        records: list[dict] = []
        page = ""
        for _ in range(100):
            payload = self._send(
                "GET",
                f"{API}/share/list",
                credential,
                params={"limit": "100", "page_token": page},
            )
            batch = payload.get("data")
            if batch is None:
                batch = payload.get("list") or []
            if not isinstance(batch, list):
                raise TransferFailed()
            for item in batch:
                if isinstance(item, dict):
                    records.append(_share_record(item))
            page = payload.get("next_page_token") if isinstance(payload.get("next_page_token"), str) else ""
            if not page:
                return records
        raise TransferFailed()

    def create_share(
        self,
        cookie: str,
        fs_id: int | None,
        password: str,
        period: str = "0",
        path: str | None = None,
        name: str | None = None,
        *,
        sleeper: Callable[[float], None] | None = None,
    ) -> tuple[str, str]:
        credential = self._live(_loads(cookie))
        fid = _fid(path or "")
        if not fid:
            raise TransferFailed()
        days = {"0": "-1", "1": "1", "7": "7", "30": "30"}.get(period, "-1")
        body: dict = {
            "file_ids": [fid],
            "share_to": "copy",
            "title": name or "分享",
            "expiration_days": days,
            "restore_limit": "-1",
            "params": {"withPassCodeInLink": "true"},
        }
        created = self._send("POST", f"{API}/share", credential, body=body)
        share_id = created.get("share_id")
        url = created.get("share_url") if isinstance(created.get("share_url"), str) else ""
        if not url and isinstance(share_id, str) and share_id:
            url = f"https://pan.xunlei.com/s/{share_id}"
        returned = created.get("pass_code") if isinstance(created.get("pass_code"), str) else ""
        code = returned.strip()
        if not url or not code:
            raise TransferFailed()
        base = url.split("#", 1)[0].split("?", 1)[0]
        return f"{base}?pwd={code}#", code

    def _live(self, credential: dict, *, action: str = "GET:/drive/v1/files") -> dict:
        if credential.get("captcha_token"):
            self._remember(credential)
            return credential
        return self._captcha(credential, action)

    def _captcha(self, credential: dict, action: str) -> dict:
        timestamp = str(int(time.time() * 1000))
        device_id = credential["device_id"]
        client_id = _client_id(credential)
        if client_id == LOGIN_CLIENT_ID:
            body = {
                "action": action,
                "captcha_token": credential.get("captcha_token") or "",
                "client_id": client_id,
                "device_id": device_id,
                "meta": {"timestamp": timestamp},
            }
        else:
            body = {
                "action": action,
                "captcha_token": credential.get("captcha_token") or "",
                "client_id": CLIENT_ID,
                "device_id": device_id,
                "meta": {
                    "client_version": CLIENT_VERSION,
                    "package_name": PACKAGE_NAME,
                    "user_id": credential.get("user_id") or "",
                    "timestamp": timestamp,
                    "captcha_sign": _captcha_sign(device_id, timestamp),
                },
                "redirect_uri": "xlaccsdk01://xunlei.com/callback?state=harbor",
            }
        payload = self._post_json(
            f"{AUTH}/shield/captcha/init",
            credential,
            body,
            authorized=False,
        )
        token = payload.get("captcha_token")
        if not isinstance(token, str) or not token:
            raise LoginRejected()
        credential["captcha_token"] = token
        self._remember(credential)
        return credential

    def _refresh(self, credential: dict) -> dict:
        client_id = _client_id(credential)
        body = {
            "grant_type": "refresh_token",
            "refresh_token": credential["refresh_token"],
            "client_id": client_id,
        }
        if client_id == CLIENT_ID:
            body["client_secret"] = CLIENT_SECRET
        payload = self._post_json(
            f"{AUTH}/auth/token",
            credential,
            body,
            authorized=False,
        )
        access = payload.get("access_token")
        refresh = payload.get("refresh_token")
        if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
            raise LoginRejected()
        credential["access_token"] = access
        credential["refresh_token"] = refresh
        credential["captcha_token"] = ""
        return self._captcha(credential, "GET:/drive/v1/files")

    def _send(
        self,
        method: str,
        url: str,
        credential: dict,
        *,
        params: dict | None = None,
        body: dict | None = None,
        invalid: bool = False,
        action: str | None = None,
        _retried: bool = False,
    ) -> dict:
        try:
            response = self.client.request(
                method,
                url,
                params=params,
                json=body,
                headers=self._headers(credential),
                timeout=20,
            )
        except Exception as exc:
            raise TransferFailed() from exc
        if response.status_code == 429:
            raise RateLimited()
        payload = _json_body(response)
        code = _error_code(payload)
        if not _retried and (response.status_code == 401 or code in _TOKEN_ERRORS):
            credential = self._refresh(credential)
            return self._send(method, url, credential, params=params, body=body, invalid=invalid, action=action, _retried=True)
        if not _retried and code == 9:
            credential["captcha_token"] = ""
            credential = self._captcha(credential, action or _action(method, url))
            return self._send(method, url, credential, params=params, body=body, invalid=invalid, action=action, _retried=True)
        if response.status_code >= 400 or _error_text(payload):
            _raise_api(payload, invalid=invalid)
        self._remember(credential)
        return payload

    def _post_json(self, url: str, credential: dict, body: dict, *, authorized: bool) -> dict:
        headers = self._headers(credential)
        if not authorized:
            headers.pop("Authorization", None)
            headers.pop("X-Captcha-Token", None)
        try:
            response = self.client.post(url, json=body, headers=headers, timeout=20)
            payload = _json_body(response)
        except Exception as exc:
            raise LoginRejected() from exc
        if response.status_code >= 400 or not payload:
            raise LoginRejected()
        return payload

    def _headers(self, credential: dict) -> dict[str, str]:
        client_id = _client_id(credential)
        headers = {
            "Authorization": f"Bearer {credential['access_token']}",
            "User-Agent": LOGIN_USER_AGENT if client_id == LOGIN_CLIENT_ID else USER_AGENT,
            "x-device-id": credential["device_id"],
            "x-client-id": client_id,
            "x-client-version": "0.0.1" if client_id == LOGIN_CLIENT_ID else CLIENT_VERSION,
        }
        token = credential.get("captcha_token")
        if isinstance(token, str) and token:
            headers["X-Captcha-Token"] = token
        return headers

    def _remember(self, credential: dict) -> str:
        dumped = json.dumps(credential, separators=(",", ":"), sort_keys=True)
        self.warmed = dumped
        return dumped


def _client_id(credential: dict) -> str:
    client_id = credential.get("client_id")
    if client_id == LOGIN_CLIENT_ID:
        return LOGIN_CLIENT_ID
    return CLIENT_ID


def _loads(cookie: str) -> dict:
    try:
        payload = json.loads(cookie)
    except json.JSONDecodeError as exc:
        raise LoginRejected() from exc
    if not isinstance(payload, dict):
        raise LoginRejected()
    for key in ("access_token", "refresh_token", "device_id", "user_id"):
        if not isinstance(payload.get(key), str) or not payload[key]:
            raise LoginRejected()
    return payload


def _captcha_sign(device_id: str, timestamp: str) -> str:
    raw = f"{CLIENT_ID}{CLIENT_VERSION}{PACKAGE_NAME}{device_id}{timestamp}"
    for algorithm in ALGORITHMS:
        raw = hashlib.md5((raw + algorithm).encode()).hexdigest()
    return "1." + raw


def _action(method: str, url: str) -> str:
    return f"{method}:{urlparse(url).path}"


def _json_body(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _error_code(payload: dict) -> int | None:
    value = payload.get("error_code")
    if isinstance(value, int):
        return value
    return None


def _error_text(payload: dict) -> str:
    for key in ("error", "error_description", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value and value not in {"OK", "success"}:
            return value
    return ""


def _raise_api(payload: dict, *, invalid: bool) -> None:
    text = _error_text(payload)
    if "提取码" in text or "pass_code" in text:
        raise WrongPassword()
    if "未登录" in text or "unauthenticated" in text or _error_code(payload) in _TOKEN_ERRORS:
        raise LoginRejected()
    if "同名" in text or "duplicate" in text:
        raise DuplicateName()
    if invalid or "not_found" in text or "不存在" in text:
        raise InvalidLink()
    raise TransferFailed()


def _fid(directory: str) -> str:
    cleaned = directory.strip().rstrip("/")
    if cleaned in {"", "/"}:
        return ""
    return cleaned.rsplit("/", 1)[-1]


def _share_id(value: str) -> str:
    marker = "pan.xunlei.com/s/"
    if marker in value:
        return value.split(marker, 1)[1].split("?", 1)[0].strip("/")
    return value


def _entry(item: dict) -> DirEntry:
    fid = item.get("id") if isinstance(item.get("id"), str) else ""
    name = item.get("name") if isinstance(item.get("name"), str) else fid
    kind = item.get("kind") if isinstance(item.get("kind"), str) else ""
    return DirEntry(
        name=name or fid,
        path=f"/{fid}",
        is_dir=kind == "drive#folder",
        size=_number(item.get("size")),
        created_at=_timestamp(item.get("created_time")),
        modified_at=_timestamp(item.get("modified_time")),
        fs_id=None,
    )


def _number(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _timestamp(value: object) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(parsed.timestamp())


def _optional_count(item: dict, key: str) -> int | None:
    if key not in item or isinstance(item.get(key), bool):
        return None
    return _number(item.get(key))


def _share_record(item: dict) -> dict:
    share_id = item.get("share_id") if isinstance(item.get("share_id"), str) else ""
    url = item.get("share_url") if isinstance(item.get("share_url"), str) else ""
    if not url and share_id:
        url = f"https://pan.xunlei.com/s/{share_id}"
    title = item.get("title") if isinstance(item.get("title"), str) else ""
    record = {
        "shareId": share_id,
        "url": url,
        "title": title,
        "views": _optional_count(item, "view_count"),
        "transfers": _optional_count(item, "restore_count"),
        "downloads": _optional_count(item, "download_count"),
    }
    created = _timestamp(item.get("create_time"))
    if created is not None:
        record["ctime"] = created
    return record
