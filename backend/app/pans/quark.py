import base64
import hashlib
import json
import mimetypes
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import format_datetime

import httpx

from app.pans.baidu import DirEntry, DownloadStream
from app.pans.errors import (
    DuplicateName,
    InvalidLink,
    LoginRejected,
    PathNotFound,
    RateLimited,
    TransferFailed,
    UploadCancelled,
    WrongPassword,
)

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
        if not isinstance(payload, dict) or payload.get("status") != 200:
            raise LoginRejected()
        data = payload.get("data")
        nickname = data.get("nickname") if isinstance(data, dict) else None
        if isinstance(nickname, str) and nickname.strip():
            return nickname.strip()
        return "夸克用户"

    def _params(self, extra: dict | None = None) -> dict:
        merged = dict(PARAMS)
        if extra:
            merged.update(extra)
        return merged

    def _payload(self, response: httpx.Response, *, invalid: bool = False) -> dict:
        if response.status_code == 429:
            raise RateLimited()
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
        if "提取码" in text:
            raise WrongPassword()
        if "未登录" in text or payload.get("status") in {401, 403}:
            raise LoginRejected()
        if "同名" in text:
            raise DuplicateName()
        if invalid:
            raise InvalidLink()
        raise TransferFailed()

    def _get(self, path: str, cookie: str, params: dict, *, invalid: bool = False) -> dict:
        try:
            response = self.client.get(
                f"{BASE}{path}",
                params=self._params(params),
                headers=self._headers(cookie),
                timeout=20,
            )
        except Exception as exc:
            raise TransferFailed() from exc
        return self._payload(response, invalid=invalid)

    def _post(self, path: str, cookie: str, body: dict, *, invalid: bool = False) -> dict:
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
        return self._payload(response, invalid=invalid)

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
            entries.append(
                DirEntry(
                    name=name,
                    path=f"/{fid}",
                    is_dir=item.get("file_type") == 0,
                    size=size if isinstance(size, int) else None,
                    created_at=_seconds(item.get("created_at")),
                    modified_at=_seconds(item.get("updated_at")),
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

    def ensure_dir(self, cookie: str, path: str) -> None:
        return None

    def ensure_subdir(self, cookie: str, dest: str, relative_dir: str) -> str:
        relative = relative_dir.replace("\\", "/").strip("/")
        current = dest.strip() or "/"
        if not relative:
            return current
        for name in relative.split("/"):
            if not name:
                continue
            match = next((entry for entry in self.list_dir(cookie, current) if entry.is_dir and entry.name == name), None)
            if match is not None:
                current = match.path
            else:
                current = self.create_dir(cookie, current, name).path
        return current

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
        data = stream.read()
        if size and len(data) != size:
            raise TransferFailed("文件大小不一致")
        actual = len(data)
        md5_hex = hashlib.md5(data).hexdigest()
        sha1_hex = hashlib.sha1(data).hexdigest()
        mime, _ = mimetypes.guess_type(filename)
        mime = mime or "application/octet-stream"
        now_ms = int(time.time() * 1000)
        pre = self._post(
            "/file/upload/pre",
            cookie,
            {
                "ccp_hash_update": True,
                "dir_name": "",
                "file_name": filename,
                "format_type": mime,
                "l_created_at": now_ms,
                "l_updated_at": now_ms,
                "pdir_fid": _fid(dest_dir),
                "size": actual,
            },
        )
        pre_data = pre.get("data") if isinstance(pre.get("data"), dict) else {}
        task_id = pre_data.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise TransferFailed()
        hashed = self._post("/file/update/hash", cookie, {"md5": md5_hex, "sha1": sha1_hex, "task_id": task_id})
        hash_data = hashed.get("data") if isinstance(hashed.get("data"), dict) else {}
        if hash_data.get("finish") is True:
            if on_progress:
                on_progress(actual)
            return
        metadata = pre.get("metadata") if isinstance(pre.get("metadata"), dict) else {}
        part_size = metadata.get("part_size")
        if not isinstance(part_size, int) or part_size <= 0:
            part_size = 4 * 1024 * 1024
        etags: list[str] = []
        part_number = 1
        offset = 0
        while offset < actual:
            if should_stop and should_stop():
                raise UploadCancelled()
            chunk = data[offset : offset + part_size]
            etag = self._upload_part(cookie, pre_data, mime, part_number, chunk)
            etags.append(etag)
            offset += len(chunk)
            if on_progress:
                on_progress(len(chunk))
            part_number += 1
        self._upload_commit(cookie, pre_data, etags)
        self._post("/file/upload/finish", cookie, {"obj_key": pre_data.get("obj_key"), "task_id": task_id})

    def _upload_auth(self, cookie: str, auth_info: object, auth_meta: str, task_id: str) -> str:
        payload = self._post(
            "/file/upload/auth",
            cookie,
            {"auth_info": auth_info, "auth_meta": auth_meta, "task_id": task_id},
        )
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        key = data.get("auth_key")
        if not isinstance(key, str) or not key:
            raise TransferFailed()
        return key

    def _oss_url(self, pre_data: dict) -> str:
        bucket = pre_data.get("bucket")
        upload_url = pre_data.get("upload_url")
        obj_key = pre_data.get("obj_key")
        if not isinstance(bucket, str) or not isinstance(upload_url, str) or not isinstance(obj_key, str):
            raise TransferFailed()
        host = upload_url[7:] if upload_url.startswith("http://") else upload_url[8:] if upload_url.startswith("https://") else upload_url
        return f"https://{bucket}.{host}/{obj_key}"

    def _upload_part(self, cookie: str, pre_data: dict, mime: str, part_number: int, chunk: bytes) -> str:
        now = format_datetime(datetime.now(timezone.utc), usegmt=True)
        upload_id = pre_data.get("upload_id")
        bucket = pre_data.get("bucket")
        obj_key = pre_data.get("obj_key")
        task_id = pre_data.get("task_id")
        auth_meta = (
            f"PUT\n\n{mime}\n{now}\nx-oss-date:{now}\n"
            f"x-oss-user-agent:aliyun-sdk-js/6.6.1 Chrome 98.0.4758.80 on Windows 10 64-bit\n"
            f"/{bucket}/{obj_key}?partNumber={part_number}&uploadId={upload_id}"
        )
        auth_key = self._upload_auth(cookie, pre_data.get("auth_info"), auth_meta, str(task_id))
        try:
            response = self.client.put(
                self._oss_url(pre_data),
                params={"partNumber": str(part_number), "uploadId": str(upload_id)},
                headers={
                    "Authorization": auth_key,
                    "Content-Type": mime,
                    "Referer": "https://pan.quark.cn/",
                    "x-oss-date": now,
                    "x-oss-user-agent": "aliyun-sdk-js/6.6.1 Chrome 98.0.4758.80 on Windows 10 64-bit",
                },
                content=chunk,
                timeout=120,
            )
        except Exception as exc:
            raise TransferFailed() from exc
        if response.status_code != 200:
            raise TransferFailed()
        etag = response.headers.get("ETag") or response.headers.get("Etag")
        if not etag:
            raise TransferFailed()
        return etag

    def _upload_commit(self, cookie: str, pre_data: dict, etags: list[str]) -> None:
        now = format_datetime(datetime.now(timezone.utc), usegmt=True)
        parts = "".join(
            f"<Part><PartNumber>{index}</PartNumber><ETag>{etag}</ETag></Part>"
            for index, etag in enumerate(etags, 1)
        )
        xml_body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"<CompleteMultipartUpload>{parts}</CompleteMultipartUpload>"
        )
        content_md5 = base64.b64encode(hashlib.md5(xml_body.encode()).digest()).decode()
        callback_b64 = base64.b64encode(json.dumps(pre_data.get("callback")).encode()).decode()
        upload_id = pre_data.get("upload_id")
        bucket = pre_data.get("bucket")
        obj_key = pre_data.get("obj_key")
        task_id = pre_data.get("task_id")
        auth_meta = (
            f"POST\n{content_md5}\napplication/xml\n{now}\n"
            f"x-oss-callback:{callback_b64}\nx-oss-date:{now}\n"
            f"x-oss-user-agent:aliyun-sdk-js/6.6.1 Chrome 98.0.4758.80 on Windows 10 64-bit\n"
            f"/{bucket}/{obj_key}?uploadId={upload_id}"
        )
        auth_key = self._upload_auth(cookie, pre_data.get("auth_info"), auth_meta, str(task_id))
        try:
            response = self.client.post(
                self._oss_url(pre_data),
                params={"uploadId": str(upload_id)},
                headers={
                    "Authorization": auth_key,
                    "Content-MD5": content_md5,
                    "Content-Type": "application/xml",
                    "Referer": "https://pan.quark.cn/",
                    "x-oss-callback": callback_b64,
                    "x-oss-date": now,
                    "x-oss-user-agent": "aliyun-sdk-js/6.6.1 Chrome 98.0.4758.80 on Windows 10 64-bit",
                },
                content=xml_body.encode(),
                timeout=60,
            )
        except Exception as exc:
            raise TransferFailed() from exc
        if response.status_code != 200:
            raise TransferFailed()

    def rename(self, cookie: str, path: str, new_name: str) -> None:
        self._post("/file/rename", cookie, {"fid": _fid(path), "file_name": new_name})

    def delete(self, cookie: str, path: str) -> None:
        self._post("/file/delete", cookie, {"action_type": 2, "filelist": [_fid(path)], "exclude_fids": []})

    def copy(self, cookie: str, path: str, dest: str, new_name: str) -> None:
        existing = self.list_dir(cookie, dest)
        if any(entry.name == new_name for entry in existing):
            raise DuplicateName()
        before = {entry.path for entry in existing}
        created = self._post(
            "/file/copy",
            cookie,
            {"filelist": [_fid(path)], "to_pdir_fid": _fid(dest), "exclude_fids": []},
        )
        data = created.get("data") if isinstance(created.get("data"), dict) else {}
        task_id = data.get("task_id")
        if isinstance(task_id, str) and task_id:
            self._wait_task(cookie, task_id, time.sleep)
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
        wait = sleeper or time.sleep
        pwd_id = _pwd_id(surl)
        token = self._post(
            "/share/sharepage/token",
            cookie,
            {"pwd_id": pwd_id, "passcode": password or ""},
            invalid=True,
        )
        data = token.get("data") if isinstance(token.get("data"), dict) else {}
        stoken = data.get("stoken")
        if not isinstance(stoken, str) or not stoken:
            raise InvalidLink()
        detail = self._get(
            "/share/sharepage/detail",
            cookie,
            {"pwd_id": pwd_id, "stoken": stoken, "pdir_fid": "0", "_page": 1, "_size": 50},
            invalid=True,
        )
        listed = detail.get("data") if isinstance(detail.get("data"), dict) else {}
        files = listed.get("list") or []
        fids = []
        tokens = []
        if isinstance(files, list):
            for item in files:
                if not isinstance(item, dict):
                    continue
                fid = item.get("fid")
                share_token = item.get("share_fid_token")
                if isinstance(fid, str) and fid and isinstance(share_token, str) and share_token:
                    fids.append(fid)
                    tokens.append(share_token)
        if not fids:
            raise InvalidLink()
        saved = self._post(
            "/share/sharepage/save",
            cookie,
            {
                "fid_list": fids,
                "fid_token_list": tokens,
                "to_pdir_fid": _fid(directory),
                "pwd_id": pwd_id,
                "stoken": stoken,
                "pdir_fid": "0",
                "scene": "link",
            },
        )
        task_data = saved.get("data") if isinstance(saved.get("data"), dict) else {}
        task_id = task_data.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise TransferFailed()
        self._wait_task(cookie, task_id, wait)

    def open_download(self, cookie: str, path: str):
        payload = self._post("/file/download", cookie, {"fids": [_fid(path)]})
        data = payload.get("data")
        first = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
        url = first.get("download_url")
        if not isinstance(url, str) or not url:
            raise TransferFailed()
        try:
            response = self.client.get(url, headers=self._headers(cookie), timeout=30)
        except Exception as exc:
            raise TransferFailed() from exc
        if response.status_code != 200:
            raise TransferFailed()
        length = response.headers.get("content-length")
        size = int(length) if isinstance(length, str) and length.isdecimal() else len(response.content)
        body = response.content

        def chunks():
            yield body

        return DownloadStream(chunks(), size)

    def list_share_records(self, cookie: str) -> list[dict]:
        records: list[dict] = []
        for page in range(1, 101):
            payload = self._get("/share/mypage/detail", cookie, {"_page": page, "_size": 50})
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            batch = data.get("list") or []
            if not isinstance(batch, list):
                raise TransferFailed()
            for item in batch:
                if isinstance(item, dict):
                    records.append(_share_record(item))
            if len(batch) < 50:
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
        wait = sleeper or time.sleep
        fid = _fid(path or "")
        if fid == "0":
            raise TransferFailed()
        expired_type = {"0": 1, "1": 3, "7": 2, "30": 4}.get(period, 1)
        code = (password or "").strip()
        body = {
            "fid_list": [fid],
            "title": name or "分享",
            "url_type": 2 if code else 1,
            "expired_type": expired_type,
        }
        if code:
            body["passcode"] = code
        created = self._post("/share", cookie, body)
        task_data = created.get("data") if isinstance(created.get("data"), dict) else {}
        task_id = task_data.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise TransferFailed()
        finished = self._wait_task(cookie, task_id, wait)
        share_id = finished.get("share_id")
        if not isinstance(share_id, str) or not share_id:
            raise TransferFailed()
        shared = self._post("/share/password", cookie, {"share_id": share_id})
        data = shared.get("data") if isinstance(shared.get("data"), dict) else {}
        url = data.get("share_url")
        returned = data.get("passcode") if isinstance(data.get("passcode"), str) else ""
        saved = returned or code
        if not isinstance(url, str) or not url:
            raise TransferFailed()
        if code and not saved:
            raise TransferFailed()
        return url, saved if code else ""

    def _wait_task(self, cookie: str, task_id: str, sleeper: Callable[[float], None]) -> dict:
        for index in range(30):
            payload = self._get("/task", cookie, {"task_id": task_id, "retry_index": index})
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            state = data.get("status")
            if state == 2:
                return data
            message = data.get("message") if isinstance(data.get("message"), str) else ""
            if state not in {0, 1, None} or "同名" in message:
                if "同名" in message:
                    raise DuplicateName()
                raise TransferFailed()
            sleeper(1)
        raise TransferFailed()


def _optional_count(item: dict, key: str) -> int | None:
    if key not in item or isinstance(item.get(key), bool):
        return None
    value = item.get(key)
    if isinstance(value, int):
        return value
    return None


def _share_record(item: dict) -> dict:
    share_id = item.get("share_id")
    pwd_id = item.get("pwd_id") if isinstance(item.get("pwd_id"), str) else ""
    url = item.get("share_url") if isinstance(item.get("share_url"), str) else ""
    if not url and pwd_id:
        url = f"https://pan.quark.cn/s/{pwd_id}"
    title = item.get("title") if isinstance(item.get("title"), str) else item.get("file_name")
    expired_at = item.get("expired_at")
    created_at = item.get("created_at")
    record = {
        "shareId": str(share_id) if share_id is not None else "",
        "url": url,
        "title": title if isinstance(title, str) else "",
        "views": _optional_count(item, "click_pv"),
        "transfers": _optional_count(item, "save_pv"),
        "downloads": _optional_count(item, "download_pv"),
    }
    if isinstance(created_at, int):
        record["ctime"] = created_at // 1000 if created_at >= 10**12 else created_at
    if isinstance(expired_at, int) and expired_at > 0:
        record["expiredTime"] = expired_at // 1000 if expired_at >= 10**12 else expired_at
    return record


def _pwd_id(value: str) -> str:
    matched = re.search(r"pan\.quark\.cn/s/([0-9A-Za-z]+)", value)
    return matched.group(1) if matched is not None else value


def _seconds(value: object) -> int | None:
    if not isinstance(value, int):
        return None
    return value // 1000 if value >= 10**12 else value


def _fid(directory: str) -> str:
    cleaned = directory.strip().rstrip("/")
    if cleaned in {"", "/"}:
        return "0"
    return cleaned.rsplit("/", 1)[-1]
