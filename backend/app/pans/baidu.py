from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from app.pans.errors import (
    DuplicateName,
    InvalidLink,
    LoginRejected,
    PathNotFound,
    RateLimited,
    TransferFailed,
    WrongPassword,
)

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

    def _headers(self, cookie: str) -> dict[str, str]:
        return {"Cookie": cookie, "User-Agent": USER_AGENT}

    def _get(self, url: str, params: dict, cookie: str) -> dict:
        try:
            response = self.client.get(
                url, params=params, headers=self._headers(cookie), timeout=15, follow_redirects=False
            )
        except Exception as exc:
            raise TransferFailed() from exc
        return _payload(response)

    def _post(self, url: str, params: dict, data: dict, cookie: str) -> dict:
        try:
            response = self.client.post(
                url,
                params=params,
                data=data,
                headers={**self._headers(cookie), "Content-Type": "application/x-www-form-urlencoded"},
                timeout=20,
                follow_redirects=False,
            )
        except Exception as exc:
            raise TransferFailed() from exc
        return _payload(response)

    def list_dir(self, cookie: str, directory: str) -> list[DirEntry]:
        try:
            payload = self._get(
                LIST_URL,
                {
                    "method": "list",
                    "dir": directory,
                    "order": "name",
                    "desc": 0,
                    "start": 0,
                    "limit": 1000,
                    "folder": 0,
                    "web": 1,
                },
                cookie,
            )
        except TransferFailed as exc:
            raise PathNotFound() from exc
        errno = payload.get("errno")
        _raise_common(errno)
        if errno in MISSING_DIR or errno != 0:
            raise PathNotFound()
        entries: list[DirEntry] = []
        for item in payload.get("list") or []:
            if not isinstance(item, dict):
                continue
            name = item.get("server_filename")
            path = item.get("path")
            if not isinstance(name, str) or not isinstance(path, str):
                continue
            entries.append(DirEntry(name=name, path=path, is_dir=item.get("isdir") == 1))
        return entries

    def transfer_share(self, cookie: str, surl: str, password: str | None, directory: str) -> None:
        token_payload = self._get(
            TOKEN_URL,
            {"clienttype": 0, "app_id": 250528, "web": 1, "fields": '["bdstoken"]'},
            cookie,
        )
        _raise_common(token_payload.get("errno"))
        if token_payload.get("errno") != 0:
            raise TransferFailed()
        result = token_payload.get("result")
        bdstoken = result.get("bdstoken") if isinstance(result, dict) else None
        if not isinstance(bdstoken, str):
            raise TransferFailed()
        verified = self._post(
            VERIFY_URL,
            {
                "surl": surl,
                "channel": "chunlei",
                "web": 1,
                "app_id": 250528,
                "clienttype": 0,
                "bdstoken": bdstoken,
            },
            {"pwd": password or ""},
            cookie,
        )
        errno = verified.get("errno")
        _raise_common(errno)
        if errno in BAD_PASSWORD:
            raise WrongPassword()
        if errno in BAD_LINK:
            raise InvalidLink()
        randsk = verified.get("randsk")
        if errno != 0 or not isinstance(randsk, str) or not randsk:
            raise InvalidLink()
        fsids: list[int] = []
        share_id = None
        uk = None
        for page in range(1, 21):
            listed = self._get(
                SHARE_LIST_URL,
                {
                    "shorturl": surl,
                    "root": 1,
                    "page": page,
                    "num": 100,
                    "web": 1,
                    "channel": "chunlei",
                    "app_id": 250528,
                    "clienttype": 0,
                },
                cookie + "; BDCLND=" + randsk,
            )
            _raise_common(listed.get("errno"))
            if listed.get("errno") in BAD_LINK or listed.get("errno") != 0:
                raise InvalidLink()
            if share_id is None:
                share_id = listed.get("share_id")
                uk = listed.get("uk")
            page_items = listed.get("list") or []
            if not isinstance(page_items, list):
                raise TransferFailed()
            for item in page_items:
                if isinstance(item, dict) and isinstance(item.get("fs_id"), int):
                    fsids.append(item["fs_id"])
            if len(page_items) < 100:
                break
        else:
            raise TransferFailed()
        if not fsids or not isinstance(share_id, int) or not isinstance(uk, int):
            raise InvalidLink()
        saved = self._post(
            TRANSFER_URL,
            {
                "shareid": share_id,
                "from": uk,
                "sekey": randsk,
                "ondup": "fail",
                "async": 0,
                "channel": "chunlei",
                "web": 1,
                "app_id": 250528,
                "clienttype": 0,
                "bdstoken": bdstoken,
            },
            {"fsidlist": json.dumps(fsids, separators=(",", ":")), "path": directory},
            cookie,
        )
        errno = saved.get("errno")
        _raise_common(errno)
        if errno in DUPLICATE:
            raise DuplicateName()
        if errno != 0:
            raise TransferFailed()


LIST_URL = "https://pan.baidu.com/rest/2.0/xpan/file"
TOKEN_URL = "https://pan.baidu.com/api/gettemplatevariable"
VERIFY_URL = "https://pan.baidu.com/share/verify"
SHARE_LIST_URL = "https://pan.baidu.com/share/list"
TRANSFER_URL = "https://pan.baidu.com/share/transfer"
RATE_LIMIT = {31034, 9019}
BAD_PASSWORD = {-9, -12}
BAD_LINK = {2, 105, 110, 111, 115, 116}
MISSING_DIR = {-9, -7}
DUPLICATE = {-33, 12}


@dataclass(frozen=True)
class DirEntry:
    name: str
    path: str
    is_dir: bool


def _payload(response: httpx.Response) -> dict:
    if response.status_code != 200:
        raise TransferFailed()
    try:
        data = response.json()
    except Exception as exc:
        raise TransferFailed() from exc
    if not isinstance(data, dict):
        raise TransferFailed()
    return data


def _raise_common(errno: object) -> None:
    if errno in RATE_LIMIT:
        raise RateLimited()
    if errno == -6:
        raise LoginRejected()
