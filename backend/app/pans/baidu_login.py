import json
import time
import uuid
from dataclasses import dataclass

import httpx

from app.pans.baidu import USER_AGENT


class QrLoginFailed(Exception):
    pass


@dataclass
class StartedQr:
    sign: str
    gid: str
    image: bytes
    content_type: str


@dataclass
class PolledQr:
    state: str
    cookie: str | None = None


def _parse_body(text: str) -> dict:
    raw = text.strip()
    if not raw.startswith("{") and not raw.startswith("["):
        start = raw.find("(")
        end = raw.rfind(")")
        if start < 0 or end <= start:
            raise QrLoginFailed()
        raw = raw[start + 1 : end]
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise QrLoginFailed()
    return data


def _get(client: httpx.Client, url: str, params: dict | None = None) -> httpx.Response:
    # An empty params dict replaces the query string already present on url.
    try:
        return client.get(
            url,
            params=params,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
                "Referer": "https://pan.baidu.com/",
            },
            timeout=8,
            follow_redirects=False,
        )
    except Exception as exc:
        raise QrLoginFailed() from exc


def _absolute_image_url(imgurl: str) -> str:
    if imgurl.startswith("https://") or imgurl.startswith("http://"):
        return imgurl
    if imgurl.startswith("//"):
        return "https:" + imgurl
    return "https://" + imgurl.lstrip("/")


def start_qr(client: httpx.Client) -> StartedQr:
    gid = str(uuid.uuid4())
    now = int(time.time() * 1000)
    # Same query the pan.baidu.com login widget sends. Without logPage the
    # code is a generic passport link, and the netdisk app opens it as a page
    # instead of a login confirmation.
    log_page = f"traceId:pc_loginv5_{now // 1000},logPage:loginv5"
    response = _get(
        client,
        "https://passport.baidu.com/v2/api/getqrcode",
        {
            "lp": "pc",
            "qrloginfrom": "pc",
            "gid": gid,
            "apiver": "v3",
            "tt": now,
            "tpl": "netdisk",
            "logPage": log_page,
        },
    )
    if response.status_code != 200:
        raise QrLoginFailed()
    try:
        payload = _parse_body(response.text)
    except Exception as exc:
        raise QrLoginFailed() from exc
    sign = payload.get("sign")
    imgurl = payload.get("imgurl")
    if payload.get("errno") not in (0, None) or not isinstance(sign, str) or not sign:
        raise QrLoginFailed()
    if not isinstance(imgurl, str) or not imgurl.strip():
        raise QrLoginFailed()
    image_response = _get(client, _absolute_image_url(imgurl))
    if image_response.status_code != 200 or not image_response.content:
        raise QrLoginFailed()
    content_type = (
        image_response.headers.get("content-type", "image/png").split(";")[0].strip()
        or "image/png"
    )
    return StartedQr(
        sign=sign, gid=gid, image=image_response.content, content_type=content_type
    )


def _cookie_from_login(response: httpx.Response) -> str:
    parts: list[str] = []
    for name in ("BDUSS", "STOKEN", "PTOKEN"):
        value = response.cookies.get(name)
        if isinstance(value, str) and value:
            parts.append(f"{name}={value}")
    if not any(part.startswith("BDUSS=") for part in parts):
        raise QrLoginFailed()
    return "; ".join(parts)


def poll_qr(client: httpx.Client, sign: str, gid: str) -> PolledQr:
    now = int(time.time() * 1000)
    response = _get(
        client,
        "https://passport.baidu.com/channel/unicast",
        {
            "channel_id": sign,
            "tpl": "netdisk",
            "gid": gid,
            "callback": "cb",
            "_sdkFrom": "1",
            "apiver": "v3",
            "tt": now,
            "_": now,
        },
    )
    if response.status_code != 200:
        return PolledQr("waiting")
    try:
        payload = _parse_body(response.text)
    except Exception:
        return PolledQr("waiting")
    if payload.get("errno") != 0:
        return PolledQr("waiting")
    channel = payload.get("channel_v")
    if isinstance(channel, str):
        try:
            channel = json.loads(channel)
        except json.JSONDecodeError:
            return PolledQr("waiting")
    if not isinstance(channel, dict):
        return PolledQr("waiting")
    if channel.get("status") not in (0, "0"):
        return PolledQr("scanned")
    token = channel.get("v")
    if not isinstance(token, str) or not token:
        return PolledQr("waiting")
    login = _get(
        client,
        "https://passport.baidu.com/v3/login/main/qrbdusslogin",
        {
            "bduss": token,
            "u": "https://pan.baidu.com/disk/home",
            "loginVersion": "v5",
            "qrcode": "1",
            "tpl": "netdisk",
            "apiver": "v3",
            "tt": str(now),
            "time": str(now // 1000),
        },
    )
    if login.status_code not in (200, 302):
        raise QrLoginFailed()
    return PolledQr("ready", _cookie_from_login(login))
