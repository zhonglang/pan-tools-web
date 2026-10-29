from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

import httpx

from app.pans.errors import (
    DuplicateName,
    InvalidLink,
    LoginRejected,
    NotAFile,
    PathNotFound,
    RateLimited,
    TransferFailed,
    UploadCancelled,
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

    def _get(
        self, url: str, params: dict, cookie: str, referer: str | None = None
    ) -> dict:
        headers = self._headers(cookie)
        if referer:
            headers["Referer"] = referer
        try:
            response = self.client.get(
                url, params=params, headers=headers, timeout=15, follow_redirects=False
            )
        except Exception as exc:
            raise TransferFailed() from exc
        return _payload(response)

    def _post(
        self,
        url: str,
        params: dict,
        data: dict,
        cookie: str,
        referer: str | None = None,
    ) -> dict:
        headers = {
            **self._headers(cookie),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if referer:
            headers["Referer"] = referer
        try:
            response = self.client.post(
                url,
                params=params,
                data=data,
                headers=headers,
                timeout=20,
                follow_redirects=False,
            )
        except Exception as exc:
            raise TransferFailed() from exc
        return _payload(response)

    def list_dir(self, cookie: str, directory: str) -> list[DirEntry]:
        raw: list[dict] = []
        start = 0
        while True:
            try:
                payload = self._get(
                    LIST_URL,
                    {
                        "method": "list",
                        "dir": directory,
                        "order": "name",
                        "desc": 0,
                        "start": start,
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
            batch = payload.get("list") or []
            if not isinstance(batch, list):
                break
            raw.extend(item for item in batch if isinstance(item, dict))
            if len(batch) < 1000:
                break
            start += 1000
        entries: list[DirEntry] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = item.get("server_filename")
            path = item.get("path")
            if not isinstance(name, str) or not isinstance(path, str):
                continue
            size = item.get("size")
            modified = item.get("server_mtime")
            created = item.get("server_ctime")
            fs_id = item.get("fs_id")
            entries.append(
                DirEntry(
                    name=name,
                    path=path,
                    is_dir=item.get("isdir") == 1,
                    size=size if isinstance(size, int) else None,
                    created_at=created if isinstance(created, int) else None,
                    modified_at=modified if isinstance(modified, int) else None,
                    fs_id=fs_id if isinstance(fs_id, int) else None,
                )
            )
        return entries

    def prepare(self, cookie: str) -> str:
        token = self._bdstoken(cookie)
        if token:
            self._cached_token = (cookie, token)
            return cookie
        warmed = self._refresh_login(cookie)
        token = self._bdstoken(warmed)
        if not token:
            raise LoginRejected()
        self._cached_token = (warmed, token)
        return warmed

    def _token_for(self, cookie: str) -> tuple[str, str]:
        cached = getattr(self, "_cached_token", None)
        if cached and cached[0] == cookie:
            return cached
        warmed = self.prepare(cookie)
        return self._cached_token

    def _bdstoken(self, cookie: str) -> str | None:
        payload = self._get(
            TOKEN_URL,
            {"clienttype": 0, "app_id": 250528, "web": 1, "fields": '["bdstoken"]'},
            cookie,
        )
        errno = payload.get("errno")
        if errno in RATE_LIMIT:
            raise RateLimited()
        if errno != 0:
            return None
        result = payload.get("result")
        token = result.get("bdstoken") if isinstance(result, dict) else None
        if isinstance(token, str) and token:
            return token
        return None

    def _refresh_login(self, cookie: str) -> str:
        jar = _cookie_jar(cookie)
        url = "https://pan.baidu.com/disk/home"
        for _ in range(8):
            try:
                response = self.client.get(
                    url,
                    headers={
                        "Cookie": _cookie_header(jar),
                        "User-Agent": USER_AGENT,
                        "Referer": "https://pan.baidu.com/",
                    },
                    timeout=15,
                    follow_redirects=False,
                )
            except Exception as exc:
                raise TransferFailed() from exc
            for name, value in response.cookies.items():
                if value:
                    jar[name] = value
            if response.status_code not in {301, 302, 303, 307, 308}:
                break
            loc = response.headers.get("location") or ""
            if loc.startswith("/"):
                loc = "https://pan.baidu.com" + loc
            host = loc.split("/")[2] if loc.startswith("https://") else ""
            if not host.endswith("baidu.com"):
                break
            url = loc
        return _cookie_header(jar)

    def transfer_share(
        self, cookie: str, surl: str, password: str | None, directory: str
    ) -> None:
        cookie, bdstoken = self._token_for(cookie)
        referer = f"https://pan.baidu.com/share/init?surl={surl}"
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
            referer,
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
                _cookie_header({**_cookie_jar(cookie), "BDCLND": randsk}),
                referer,
            )
            _raise_common(listed.get("errno"))
            if listed.get("errno") in BAD_LINK or listed.get("errno") != 0:
                raise InvalidLink()
            if share_id is None:
                share_id = _number(listed.get("share_id"))
                uk = _number(listed.get("uk"))
            page_items = listed.get("list") or []
            if not isinstance(page_items, list):
                raise TransferFailed()
            for item in page_items:
                if not isinstance(item, dict):
                    continue
                fs_id = _number(item.get("fs_id"))
                if fs_id is not None:
                    fsids.append(fs_id)
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
                "sekey": unquote(randsk),
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
            referer,
        )
        errno = saved.get("errno")
        _raise_common(errno)
        if errno in DUPLICATE:
            raise DuplicateName()
        if errno != 0:
            raise TransferFailed()

    def create_dir(self, cookie: str, path: str) -> None:
        cookie, bdstoken = self._token_for(cookie)
        created = self._post(
            CREATE_URL,
            {
                "a": "commit",
                "bdstoken": bdstoken,
                "clienttype": 0,
                "app_id": 250528,
                "web": 1,
            },
            {"path": path, "isdir": "1", "block_list": "[]"},
            cookie,
        )
        errno = created.get("errno")
        _raise_common(errno)
        if errno == -8:
            raise DuplicateName()
        if errno in MISSING_DIR:
            raise PathNotFound()
        if errno != 0:
            raise TransferFailed()

    def ensure_dir(self, cookie: str, path: str) -> None:
        cleaned = path.strip().rstrip("/") or "/"
        if cleaned == "/":
            return
        parts = [part for part in cleaned.split("/") if part]
        current = ""
        for part in parts:
            current = f"{current}/{part}"
            try:
                self.create_dir(cookie, current)
            except DuplicateName:
                pass

    def ensure_subdir(self, cookie: str, dest: str, relative_dir: str) -> str:
        relative = relative_dir.replace("\\", "/").strip("/")
        base = dest.strip().rstrip("/") or ""
        if not relative:
            return base or "/"
        full = f"{base}/{relative}" if base else f"/{relative}"
        if not full.startswith("/"):
            full = f"/{full}"
        self.ensure_dir(cookie, full)
        return full

    def upload_file(
        self,
        cookie: str,
        dest_dir: str,
        filename: str,
        stream,
        size: int,
        *,
        on_progress=None,
        should_stop=None,
    ) -> None:
        if should_stop and should_stop():
            raise UploadCancelled()
        path = _join_path(dest_dir, filename)
        blocks: list[bytes] = []
        digests: list[str] = []
        content_md5 = hashlib.md5()
        slice_md5 = hashlib.md5()
        remaining_slice = 256 * 1024
        while True:
            if should_stop and should_stop():
                raise UploadCancelled()
            chunk = stream.read(UPLOAD_CHUNK)
            if not chunk:
                break
            blocks.append(chunk)
            digests.append(hashlib.md5(chunk).hexdigest())
            content_md5.update(chunk)
            if remaining_slice > 0:
                take = chunk[:remaining_slice]
                slice_md5.update(take)
                remaining_slice -= len(take)
        if size and sum(len(block) for block in blocks) != size:
            raise TransferFailed("文件大小不一致")
        actual_size = sum(len(block) for block in blocks)
        cookie, bdstoken = self._token_for(cookie)
        block_list = json.dumps(digests, separators=(",", ":"))
        precreate = self._post(
            PRECREATE_URL,
            {
                "channel": "chunlei",
                "web": 1,
                "app_id": 250528,
                "clienttype": 0,
                "bdstoken": bdstoken,
            },
            {
                "path": path,
                "size": str(actual_size),
                "isdir": "0",
                "autoinit": "1",
                "rtype": "1",
                "block_list": block_list,
                "content-md5": content_md5.hexdigest(),
                "slice-md5": slice_md5.hexdigest(),
            },
            cookie,
        )
        errno = precreate.get("errno")
        _raise_common(errno)
        if errno != 0:
            raise TransferFailed()
        if precreate.get("return_type") == 2:
            if on_progress:
                on_progress(actual_size)
            return
        upload_id = precreate.get("uploadid")
        if not isinstance(upload_id, str) or not upload_id:
            raise TransferFailed()
        needed = precreate.get("block_list")
        if not isinstance(needed, list) or not needed:
            needed = list(range(len(blocks)))
        for partseq in needed:
            if should_stop and should_stop():
                raise UploadCancelled()
            index = int(partseq)
            if index < 0 or index >= len(blocks):
                raise TransferFailed()
            chunk = blocks[index]
            try:
                response = self.client.post(
                    UPLOAD_SLICE_URL,
                    params={
                        "method": "upload",
                        "type": "tmpfile",
                        "app_id": 250528,
                        "channel": "chunlei",
                        "clienttype": 0,
                        "web": 1,
                        "path": path,
                        "uploadid": upload_id,
                        "uploadsign": 0,
                        "partseq": index,
                    },
                    headers={"Cookie": cookie, "User-Agent": USER_AGENT},
                    files={"file": (filename, chunk, "application/octet-stream")},
                    timeout=120,
                )
            except Exception as exc:
                raise TransferFailed() from exc
            payload = _payload(response)
            if payload.get("error_code") not in (None, 0) and payload.get(
                "errno"
            ) not in (None, 0):
                raise TransferFailed()
            if on_progress:
                on_progress(len(chunk))
        created = self._post(
            CREATE_URL,
            {
                "a": "commit",
                "bdstoken": bdstoken,
                "clienttype": 0,
                "app_id": 250528,
                "web": 1,
            },
            {
                "path": path,
                "size": str(actual_size),
                "isdir": "0",
                "rtype": "1",
                "uploadid": upload_id,
                "block_list": block_list,
            },
            cookie,
        )
        errno = created.get("errno")
        _raise_common(errno)
        if errno != 0:
            raise TransferFailed()

    def rename(self, cookie: str, path: str, new_name: str) -> None:
        self._manage(cookie, "rename", [{"path": path, "newname": new_name}])

    def delete(self, cookie: str, path: str) -> None:
        self.delete_many(cookie, [path])

    def delete_many(self, cookie: str, paths: list[str]) -> None:
        targets = [path for path in paths if path]
        if not targets:
            return
        self._manage(cookie, "delete", targets)

    def copy(self, cookie: str, path: str, dest: str, new_name: str) -> None:
        self._manage(
            cookie, "copy", [{"path": path, "dest": dest, "newname": new_name}]
        )

    def create_share(
        self,
        cookie: str,
        fs_id: int,
        password: str,
        period: str = "0",
        path: str | None = None,
        name: str | None = None,
    ) -> str:
        cookie, bdstoken = self._token_for(cookie)
        created = self._post(
            SHARE_SET_URL,
            {
                "channel": "chunlei",
                "clienttype": 0,
                "web": 1,
                "app_id": 250528,
                "bdstoken": bdstoken,
            },
            {
                "schannel": "4",
                "channel_list": "[]",
                "period": period,
                "pwd": password,
                "fid_list": json.dumps([fs_id], separators=(",", ":")),
            },
            cookie,
        )
        errno = created.get("errno")
        _raise_common(errno)
        if errno != 0:
            raise TransferFailed()
        link = created.get("link")
        if not isinstance(link, str) or not link:
            shorturl = created.get("shorturl")
            if not isinstance(shorturl, str) or not shorturl:
                raise TransferFailed()
            link = f"https://pan.baidu.com/s/1{shorturl}"
        if "pwd=" not in link:
            link = f"{link}{'&' if '?' in link else '?'}pwd={password}"
        return link

    def list_share_records(self, cookie: str) -> list[dict]:
        cookie, bdstoken = self._token_for(cookie)
        records: list[dict] = []
        for page in range(1, 101):
            payload = self._get(
                SHARE_RECORD_URL,
                {
                    "page": page,
                    "num": 100,
                    "order": "ctime",
                    "desc": 1,
                    "channel": "chunlei",
                    "web": 1,
                    "app_id": 250528,
                    "clienttype": 0,
                    "bdstoken": bdstoken,
                },
                cookie,
                "https://pan.baidu.com/share/manage",
            )
            errno = payload.get("errno")
            _raise_common(errno)
            if errno != 0:
                raise TransferFailed()
            batch = payload.get("list") or []
            if not isinstance(batch, list):
                raise TransferFailed()
            records.extend(item for item in batch if isinstance(item, dict))
            if len(batch) < 100:
                return records
        raise TransferFailed()

    def open_download(self, cookie: str, path: str):
        urls = self._download_urls(cookie, path)
        for url in urls:
            response = self._range_get(cookie, url, 0, DOWNLOAD_CHUNK - 1)
            if response is None or response.status_code not in {200, 206}:
                continue
            first = response.content
            total = _content_range_total(response)

            def chunks(url=url, first=first, status=response.status_code, total=total):
                yield first
                if (
                    status == 200
                    or len(first) < DOWNLOAD_CHUNK
                    or (total is not None and len(first) >= total)
                ):
                    return
                start = len(first)
                while True:
                    nxt = self._range_get(
                        cookie, url, start, start + DOWNLOAD_CHUNK - 1
                    )
                    if nxt is None:
                        raise TransferFailed()
                    if nxt.status_code == 416 or not nxt.content:
                        return
                    yield nxt.content
                    start += len(nxt.content)
                    if len(nxt.content) < DOWNLOAD_CHUNK or (
                        total is not None and start >= total
                    ):
                        return

            status = response.status_code
            size = (
                total if total is not None else (len(first) if status == 200 else None)
            )
            return DownloadStream(chunks(), size)
        raise TransferFailed()

    def _download_urls(self, cookie: str, path: str) -> list[str]:
        try:
            response = self.client.get(
                PCS_DOWNLOAD_URL,
                params={
                    "method": "locatedownload",
                    "app_id": 250528,
                    "path": path,
                    "ver": "2.0",
                },
                headers={"Cookie": cookie, "User-Agent": PCS_UA},
                timeout=20,
                follow_redirects=False,
            )
            try:
                located = response.json()
            except Exception as exc:
                raise TransferFailed() from exc
            if not isinstance(located, dict):
                raise TransferFailed()
        except TransferFailed:
            raise
        except Exception as exc:
            raise TransferFailed() from exc
        error_code = located.get("error_code", located.get("errno"))
        if error_code == 31074:
            raise NotAFile()
        if error_code in {31066, -9}:
            raise PathNotFound()
        found: list[str] = []
        items = located.get("urls")
        if not isinstance(items, list):
            raise TransferFailed()
        for item in items:
            url = item.get("url") if isinstance(item, dict) else None
            if not isinstance(url, str):
                continue
            parsed = urlparse(url)
            host = parsed.hostname or ""
            if parsed.scheme not in {"https", "http"} or not host.endswith(
                ("baidu.com", "baidupcs.com", "baidubce.com")
            ):
                continue
            found.append(url)
        https = [url for url in found if url.startswith("https://")]
        ordered = https + [url for url in found if url not in https]
        if not ordered:
            raise TransferFailed()
        return ordered

    def _range_get(
        self, cookie: str, url: str, start: int, end: int
    ) -> httpx.Response | None:
        try:
            response = self.client.get(
                url,
                headers={
                    "User-Agent": PCS_UA,
                    "Cookie": cookie,
                    "Range": f"bytes={start}-{end}",
                },
                timeout=60,
                follow_redirects=True,
            )
        except Exception as exc:
            raise TransferFailed() from exc
        if response.status_code in {200, 206, 416}:
            return response
        return None

    def _manage(self, cookie: str, opera: str, filelist: list) -> None:
        cookie, bdstoken = self._token_for(cookie)
        result = self._post(
            FILE_MANAGER_URL,
            {
                "opera": opera,
                "async": 0,
                "onnest": "fail",
                "channel": "chunlei",
                "web": 1,
                "app_id": 250528,
                "clienttype": 0,
                "bdstoken": bdstoken,
            },
            {"filelist": json.dumps(filelist, separators=(",", ":"))},
            cookie,
        )
        errno = result.get("errno")
        _raise_common(errno)
        if errno in DUPLICATE:
            raise DuplicateName()
        if errno in MISSING_DIR:
            raise PathNotFound()
        if errno != 0:
            raise TransferFailed()


LIST_URL = "https://pan.baidu.com/rest/2.0/xpan/file"
FILE_MANAGER_URL = "https://pan.baidu.com/api/filemanager"
SHARE_SET_URL = "https://pan.baidu.com/share/set"
SHARE_RECORD_URL = "https://pan.baidu.com/share/record"
PCS_DOWNLOAD_URL = "https://pcs.baidu.com/rest/2.0/pcs/file"
PCS_UA = "netdisk;P2SP;2.2.60.26"
DOWNLOAD_CHUNK = 4 * 1024 * 1024
CREATE_URL = "https://pan.baidu.com/api/create"
PRECREATE_URL = "https://pan.baidu.com/api/precreate"
UPLOAD_SLICE_URL = "https://c3.pcs.baidu.com/rest/2.0/pcs/superfile2"
TOKEN_URL = "https://pan.baidu.com/api/gettemplatevariable"
VERIFY_URL = "https://pan.baidu.com/share/verify"
SHARE_LIST_URL = "https://pan.baidu.com/share/list"
TRANSFER_URL = "https://pan.baidu.com/share/transfer"
UPLOAD_CHUNK = 4 * 1024 * 1024
RATE_LIMIT = {31034, 9019}
BAD_PASSWORD = {-9, -12}
BAD_LINK = {2, 105, 110, 111, 115, 116}
MISSING_DIR = {-9, -7}
DUPLICATE = {-33, 12}


def _join_path(dest_dir: str, filename: str) -> str:
    base = dest_dir.strip().rstrip("/") or ""
    name = filename.lstrip("/")
    if not base:
        return f"/{name}"
    if base.startswith("/"):
        return f"{base}/{name}"
    return f"/{base}/{name}"


class DownloadStream:
    def __init__(self, chunks, size: int | None) -> None:
        self._chunks = chunks
        self.size = size

    def __iter__(self):
        return self._chunks


def stream_ranged_download(
    client: httpx.Client, url: str, headers: dict[str, str]
) -> DownloadStream:
    """Fetch a CDN URL in chunks. Validates the first range before returning the stream."""

    def range_get(start: int, end: int) -> httpx.Response | None:
        try:
            response = client.get(
                url,
                headers={**headers, "Range": f"bytes={start}-{end}"},
                timeout=60,
                follow_redirects=True,
            )
        except Exception as exc:
            raise TransferFailed() from exc
        if response.status_code in {200, 206, 416}:
            return response
        return None

    first = range_get(0, DOWNLOAD_CHUNK - 1)
    if first is None:
        raise TransferFailed()
    body = first.content
    total = _content_range_total(first)

    def chunks():
        yield body
        if (
            first.status_code == 200
            or len(body) < DOWNLOAD_CHUNK
            or (total is not None and len(body) >= total)
        ):
            return
        start = len(body)
        while True:
            nxt = range_get(start, start + DOWNLOAD_CHUNK - 1)
            if nxt is None:
                raise TransferFailed()
            if nxt.status_code == 416 or not nxt.content:
                return
            yield nxt.content
            start += len(nxt.content)
            if len(nxt.content) < DOWNLOAD_CHUNK or (
                total is not None and start >= total
            ):
                return

    size = (
        total
        if total is not None
        else (len(body) if first.status_code == 200 else None)
    )
    return DownloadStream(chunks(), size)


def stream_full_download(
    client: httpx.Client, url: str, headers: dict[str, str]
) -> DownloadStream:
    """Stream a CDN URL without Range. Needed when the host rejects ranged GETs."""
    try:
        request = client.build_request("GET", url, headers=headers)
        response = client.send(request, stream=True, follow_redirects=True)
    except Exception as exc:
        raise TransferFailed() from exc
    if response.status_code not in {200, 206}:
        response.close()
        raise TransferFailed()
    length = response.headers.get("content-length")
    size = int(length) if isinstance(length, str) and length.isdecimal() else None

    def chunks():
        try:
            yield from response.iter_bytes(1024 * 1024)
        finally:
            response.close()

    return DownloadStream(chunks(), size)


@dataclass(frozen=True)
class DirEntry:
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    created_at: int | None = None
    modified_at: int | None = None
    fs_id: int | None = None


def _number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _cookie_jar(cookie: str) -> dict[str, str]:
    jar: dict[str, str] = {}
    for part in cookie.split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name and value:
            jar[name] = value
    return jar


def _cookie_header(jar: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in jar.items())


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


def _content_range_total(response: httpx.Response) -> int | None:
    header = response.headers.get("content-range") or ""
    if "/" not in header:
        return None
    total = header.rsplit("/", 1)[-1]
    if not total.isdigit():
        return None
    return int(total)


def _raise_common(errno: object) -> None:
    if errno in RATE_LIMIT:
        raise RateLimited()
    if errno == -6:
        raise LoginRejected()
