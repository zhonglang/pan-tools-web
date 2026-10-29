import io
import uuid
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import segno

from app.pans.quark import USER_AGENT

QR_CLIENT = "532"
QR_TARGET = "https://su.quark.cn/4_eMHBJ"
QR_BIZ = "S:custom|OPT:SAREA@0|OPT:IMMERSIVE@1|OPT:BACK_BTN_STYLE@0"


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
    nickname: str | None = None


def _get(
    client: httpx.Client, url: str, params: dict, *, follow_redirects: bool = False
) -> httpx.Response:
    try:
        return client.get(
            url,
            params=params,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://pan.quark.cn",
                "Referer": "https://pan.quark.cn/",
            },
            timeout=8,
            follow_redirects=follow_redirects,
        )
    except Exception as exc:
        raise QrLoginFailed() from exc


def _members(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if not isinstance(data, dict):
        return {}
    members = data.get("members")
    return members if isinstance(members, dict) else {}


def qr_login_url(token: str) -> str:
    query = urlencode(
        {
            "token": token,
            "client_id": QR_CLIENT,
            "ssb": "weblogin",
            "uc_param_str": "",
            "uc_biz_str": QR_BIZ,
        }
    )
    return f"{QR_TARGET}?{query}"


def _qr_png(token: str) -> bytes:
    buffer = io.BytesIO()
    segno.make(qr_login_url(token), error="m").save(
        buffer, kind="png", scale=8, border=2
    )
    return buffer.getvalue()


def _set_cookies(response: httpx.Response) -> dict[str, str]:
    found: dict[str, str] = {}
    for header in response.headers.get_list("set-cookie"):
        pair = header.split(";", 1)[0].strip()
        if "=" not in pair:
            continue
        name, value = pair.split("=", 1)
        name = name.strip()
        if name and value:
            found[name] = value
    return found


def _json_object(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _exchange_ticket(
    client: httpx.Client, ticket: str
) -> tuple[str, str | None] | None:
    url = "https://pan.quark.cn/account/info"
    params: dict[str, str] | None = {"st": ticket, "lw": "scan"}
    collected: dict[str, str] = {}
    response: httpx.Response | None = None
    for _ in range(5):
        response = _get(client, url, params or {}, follow_redirects=False)
        collected.update(_set_cookies(response))
        if response.status_code not in {301, 302, 303, 307, 308}:
            break
        location = response.headers.get("location")
        if not location:
            raise QrLoginFailed()
        url = str(response.url.join(location))
        params = None
    else:
        raise QrLoginFailed()
    if response is None or response.status_code != 200 or not collected:
        raise QrLoginFailed()
    payload = _json_object(response)
    if payload.get("success") is not True:
        return None
    data = payload.get("data")
    raw_name = data.get("nickname") if isinstance(data, dict) else None
    display_name = (
        raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else None
    )
    cookie = "; ".join(f"{name}={value}" for name, value in collected.items())
    return cookie, display_name


def start_qr(client: httpx.Client) -> StartedQr:
    request_id = str(uuid.uuid4())
    response = _get(
        client,
        "https://uop.quark.cn/cas/ajax/getTokenForQrcodeLogin",
        {"client_id": QR_CLIENT, "v": "1.2", "request_id": request_id},
    )
    if response.status_code != 200:
        raise QrLoginFailed()
    try:
        payload = response.json()
    except Exception as exc:
        raise QrLoginFailed() from exc
    token = _members(payload).get("token")
    if (
        not isinstance(payload, dict)
        or payload.get("status") != 2000000
        or not isinstance(token, str)
        or not token
    ):
        raise QrLoginFailed()
    return StartedQr(
        sign=token, gid=request_id, image=_qr_png(token), content_type="image/png"
    )


def poll_qr(client: httpx.Client, token: str, _request_id: str = "") -> PolledQr:
    params = {
        "client_id": QR_CLIENT,
        "v": "1.2",
        "token": token,
        "request_id": str(uuid.uuid4()),
    }
    response = _get(
        client, "https://uop.quark.cn/cas/ajax/getServiceTicketByQrcodeToken", params
    )
    if response.status_code != 200:
        return PolledQr("waiting")
    try:
        payload = response.json()
    except Exception as exc:
        raise QrLoginFailed() from exc
    if not isinstance(payload, dict) or payload.get("status") != 2000000:
        message = payload.get("message") if isinstance(payload, dict) else ""
        if isinstance(message, str) and "过期" in message:
            return PolledQr("expired")
        return PolledQr("waiting")
    members = _members(payload)
    ticket = members.get("service_ticket")
    if not isinstance(ticket, str) or not ticket:
        if members.get("status") == 1:
            return PolledQr("scanned")
        return PolledQr("waiting")
    exchanged = _exchange_ticket(client, ticket)
    if exchanged is None:
        return PolledQr("expired")
    cookie, nickname = exchanged
    return PolledQr("ready", cookie, nickname)
