from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

import httpx

from app.models.library import LibraryItem
from app.pans.quark import BASE as QUARK_BASE
from app.pans.quark import PARAMS as QUARK_PARAMS
from app.pans.quark import USER_AGENT as QUARK_UA
from app.pans.xunlei import API as XUNLEI_API
from app.pans.xunlei import CLIENT_ID, CLIENT_VERSION, USER_AGENT as XUNLEI_UA
from app.pans.xunlei import XunleiAdapter
from app.services.links import ParsedLink, parse_share_link

BAIDU_DEAD = {2, -21, 105, 110, 111, 115, 116}
XUNLEI_ALIVE = {"OK", "PASS_CODE_ERROR"}
DEAD_WORDS = ("不存在", "失效", "过期", "取消", "删除", "违规")
PAN_ORDER = {"baidu": 0, "quark": 1, "xunlei": 2}
_BAIDU_ERRNO = re.compile(r'"errno"\s*:\s*(-?\d+)')
_BAIDU_PAGE_TYPE = re.compile(r'"share_page_type"\s*:\s*"([^"]+)"')
_thread_clients = threading.local()


@dataclass(frozen=True)
class DeadLink:
    id: int
    prefix: str
    name: str
    provider: str
    reason: str


@dataclass(frozen=True)
class LinkCheck:
    checked: int
    invalid: list[DeadLink]
    unknown: int


def classify_baidu(payload: dict) -> str:
    errno = payload.get("errno")
    if errno == 0:
        return "ok"
    if errno in BAIDU_DEAD:
        return "invalid"
    message = (
        payload.get("show_msg") if isinstance(payload.get("show_msg"), str) else ""
    )
    if any(word in message for word in DEAD_WORDS):
        return "invalid"
    if payload.get("share_page_type") == "error":
        return "invalid"
    return "unknown"


def classify_quark(payload: dict, *, now: int | None = None) -> str:
    if payload.get("status") == 200:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        expired_at = data.get("expired_at")
        if isinstance(expired_at, int) and expired_at > 0:
            seconds = expired_at // 1000 if expired_at >= 10**12 else expired_at
            if seconds <= (now if now is not None else int(time.time())):
                return "invalid"
        return "ok"
    message = payload.get("message") if isinstance(payload.get("message"), str) else ""
    if "提取码" in message:
        return "ok"
    if payload.get("status") == 404 or any(word in message for word in DEAD_WORDS):
        return "invalid"
    return "unknown"


def classify_xunlei(payload: dict) -> str:
    status = payload.get("share_status")
    if status in XUNLEI_ALIVE:
        return "ok"
    if isinstance(status, str) and status:
        return "invalid"
    if payload.get("error_code") == 9 or payload.get("error") == "captcha_invalid":
        return "unknown"
    if payload.get("error_code") == 3:
        return "invalid"
    text = " ".join(
        value
        for value in (
            payload.get("error"),
            payload.get("error_description"),
            payload.get("message"),
        )
        if isinstance(value, str)
    )
    if any(word in text for word in (*DEAD_WORDS, "not_found")):
        return "invalid"
    return "unknown"


def check_library_links(items: list[LibraryItem], client: httpx.Client) -> LinkCheck:
    jobs: list[tuple[LibraryItem, str, ParsedLink]] = []
    for item in items:
        for provider, raw in (
            ("baidu", item.baidu_url),
            ("quark", item.quark_url),
            ("xunlei", item.xunlei_url),
        ):
            parsed = parse_share_link(raw or "")
            if parsed is None or parsed.provider != provider:
                continue
            jobs.append((item, provider, parsed))
    guest = (
        _xunlei_guest(client)
        if any(provider == "xunlei" for _, provider, _ in jobs)
        else None
    )

    def run(job: tuple[LibraryItem, str, ParsedLink]) -> str:
        _item, provider, parsed = job
        # 每个任务独立 Client：共用 jar 时百度 PANPSC 会污染后续请求，把有效链接打成 404。
        with _scoped_client(client) as scoped:
            try:
                if provider == "baidu":
                    return classify_baidu(_baidu_payload(scoped, parsed))
                if provider == "quark":
                    return classify_quark(_quark_payload(scoped, parsed))
                if guest is None:
                    return "unknown"
                return classify_xunlei(_xunlei_payload(scoped, parsed, guest))
            except Exception:
                return "unknown"

    invalid: list[DeadLink] = []
    unknown = 0
    if jobs:
        with ThreadPoolExecutor(max_workers=6) as pool:
            states = list(pool.map(run, jobs))
        for (item, provider, _parsed), state in zip(jobs, states, strict=True):
            if state == "invalid":
                invalid.append(
                    DeadLink(item.id, item.prefix, item.name, provider, "链接已失效")
                )
            elif state == "unknown":
                unknown += 1
    invalid.sort(
        key=lambda hit: (
            int(hit.prefix),
            hit.prefix,
            PAN_ORDER.get(hit.provider, 9),
            hit.id,
        )
    )
    return LinkCheck(checked=len(jobs), invalid=invalid, unknown=unknown)


@contextmanager
def _scoped_client(client: httpx.Client) -> Iterator[httpx.Client]:
    """每线程独立 Client，并清空 cookie，避免 PANPSC 串请求导致误判 404。"""
    transport = client._transport
    if isinstance(transport, httpx.MockTransport):
        scoped = httpx.Client(
            transport=transport, timeout=client.timeout, follow_redirects=False
        )
        try:
            yield scoped
        finally:
            scoped.close()
        return
    scoped = getattr(_thread_clients, "client", None)
    if scoped is None:
        scoped = httpx.Client(timeout=client.timeout, follow_redirects=False)
        _thread_clients.client = scoped
    scoped.cookies.clear()
    try:
        yield scoped
    finally:
        scoped.cookies.clear()


def _baidu_payload(client: httpx.Client, parsed: ParsedLink) -> dict:
    # 不验提取码：打开分享页即可区分失效/违规与仍需提取码的有效链接。
    response = client.get(
        f"https://pan.baidu.com/s/1{parsed.surl}",
        headers={
            "User-Agent": QUARK_UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
        },
        follow_redirects=False,
    )
    if response.status_code in {301, 302, 303, 307, 308}:
        location = response.headers.get("location") or ""
        if "share/init" in location:
            return {"errno": 0}
        return {}
    if response.status_code == 404:
        return {"errno": 105}
    if response.status_code != 200:
        return {}
    text = response.text
    match = _BAIDU_ERRNO.search(text)
    page_type = _BAIDU_PAGE_TYPE.search(text)
    payload: dict = {}
    if match is not None:
        payload["errno"] = int(match.group(1))
    if page_type is not None:
        payload["share_page_type"] = page_type.group(1)
    if "errno" not in payload and payload.get("share_page_type") != "error":
        payload["errno"] = 0
    return payload


def _quark_payload(client: httpx.Client, parsed: ParsedLink) -> dict:
    response = client.post(
        f"{QUARK_BASE}/share/sharepage/token",
        params=QUARK_PARAMS,
        json={"pwd_id": parsed.surl, "passcode": parsed.password or ""},
        headers={"User-Agent": QUARK_UA},
    )
    try:
        payload = response.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _xunlei_guest(client: httpx.Client) -> dict | None:
    credential = {
        "device_id": "e" * 32,
        "user_id": "",
        "captcha_token": "",
        "access_token": "",
        "refresh_token": "",
        "client_id": CLIENT_ID,
    }
    try:
        return XunleiAdapter(client)._captcha(credential, "GET:/drive/v1/share")
    except Exception:
        return None


def _xunlei_payload(client: httpx.Client, parsed: ParsedLink, guest: dict) -> dict:
    response = client.get(
        f"{XUNLEI_API}/share",
        params={
            "share_id": parsed.surl,
            "pass_code": parsed.password or "",
            "limit": "1",
        },
        headers={
            "User-Agent": XUNLEI_UA,
            "x-device-id": guest["device_id"],
            "x-client-id": CLIENT_ID,
            "x-client-version": CLIENT_VERSION,
            "X-Captcha-Token": guest.get("captcha_token") or "",
        },
    )
    try:
        payload = response.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}
