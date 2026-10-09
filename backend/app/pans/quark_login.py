from dataclasses import dataclass

import httpx

from app.pans.quark import USER_AGENT

QR_CLIENT = "532"


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


def _get(client: httpx.Client, url: str, params: dict) -> httpx.Response:
    try:
        return client.get(
            url,
            params=params,
            headers={"User-Agent": USER_AGENT, "Accept": "*/*", "Referer": "https://pan.quark.cn/"},
            timeout=8,
            follow_redirects=False,
        )
    except Exception as exc:
        raise QrLoginFailed() from exc


def start_qr(client: httpx.Client) -> StartedQr:
    response = _get(
        client,
        "https://uop.quark.cn/cas/ajax/getTokenForQrcodeLogin",
        {"client_id": QR_CLIENT, "v": "1.2"},
    )
    if response.status_code != 200:
        raise QrLoginFailed()
    try:
        payload = response.json()
    except Exception as exc:
        raise QrLoginFailed() from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    token = data.get("token") if isinstance(data, dict) else None
    if payload.get("status") != 2000000 or not isinstance(token, str) or not token:
        raise QrLoginFailed()
    image = _get(client, "https://su.quark.cn/4_eMHBJ", {"token": token, "client_id": QR_CLIENT})
    if image.status_code != 200 or not image.content:
        raise QrLoginFailed()
    content_type = image.headers.get("content-type", "image/png").split(";")[0].strip() or "image/png"
    return StartedQr(sign=token, gid="", image=image.content, content_type=content_type)


def poll_qr(client: httpx.Client, token: str) -> PolledQr:
    response = _get(
        client,
        "https://uop.quark.cn/cas/ajax/getServiceTicketByQrcodeToken",
        {"client_id": QR_CLIENT, "v": "1.2", "token": token},
    )
    if response.status_code != 200:
        return PolledQr("expired")
    try:
        payload = response.json()
    except Exception as exc:
        raise QrLoginFailed() from exc
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else {}
    message = payload.get("message") if isinstance(payload, dict) else ""
    if isinstance(message, str) and "过期" in message:
        return PolledQr("expired")
    ticket = data.get("service_ticket")
    if isinstance(ticket, str) and ticket:
        login = _get(client, "https://uop.quark.cn/cas/ajax/loginWithServiceTicket", {"st": ticket})
        if login.status_code != 200:
            raise QrLoginFailed()
        parts = [f"{name}={value}" for name, value in login.cookies.items() if value]
        if not parts:
            raise QrLoginFailed()
        return PolledQr("ready", "; ".join(parts))
    if data.get("status") == 1:
        return PolledQr("scanned")
    return PolledQr("waiting")
