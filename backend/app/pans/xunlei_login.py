import io
import json
import time
import uuid
from urllib.parse import parse_qsl, quote, urlsplit

import httpx
import segno

from app.pans.xunlei import CLIENT_ID, CLIENT_SECRET, CLIENT_VERSION, USER_AGENT

AUTH = "https://xluser-ssl.xunlei.com/v1"


class QrLoginFailed(Exception):
    pass


class StartedQr:
    def __init__(self, sign: str, gid: str, image: bytes, content_type: str) -> None:
        self.sign = sign
        self.gid = gid
        self.image = image
        self.content_type = content_type


class PolledQr:
    def __init__(self, state: str, cookie: str | None = None, nickname: str | None = None) -> None:
        self.state = state
        self.cookie = cookie
        self.nickname = nickname


def _headers(device_id: str) -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "x-device-id": device_id,
        "x-client-id": CLIENT_ID,
        "x-client-version": CLIENT_VERSION,
    }


def _post(client: httpx.Client, url: str, device_id: str, body: dict) -> httpx.Response:
    try:
        return client.post(url, json=body, headers=_headers(device_id), timeout=8)
    except Exception as exc:
        raise QrLoginFailed() from exc


def _payload(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except Exception as exc:
        raise QrLoginFailed() from exc
    if not isinstance(payload, dict):
        raise QrLoginFailed()
    return payload


def _qr_png(content: str) -> bytes:
    buffer = io.BytesIO()
    segno.make(content, error="m").save(buffer, kind="png", scale=8, border=2)
    return buffer.getvalue()


def _scan_url(verification_uri_complete: str) -> str:
    # The app opens this URL. /device/ is the device-management page, and
    # /__/auth/device/ returns 404. The confirmation page is qrcode-login.
    parts = urlsplit(verification_uri_complete)
    if "user_code" not in dict(parse_qsl(parts.query)):
        raise QrLoginFailed()
    if parts.path.rstrip("/") == "/__/auth/device":
        return "https://i.xunlei.com/center/account/personal/qrcode-login/?" + parts.query
    return verification_uri_complete


def start_qr(client: httpx.Client) -> StartedQr:
    device_id = uuid.uuid4().hex
    response = _post(
        client,
        f"{AUTH}/auth/device/code",
        device_id,
        {"client_id": CLIENT_ID, "scope": "profile offline pan sso user", "response_type": "device_code"},
    )
    if response.status_code >= 400:
        raise QrLoginFailed()
    payload = _payload(response)
    device_code = payload.get("device_code")
    complete = payload.get("verification_uri_complete")
    user_code = payload.get("user_code")
    if not isinstance(device_code, str) or not device_code:
        raise QrLoginFailed()
    if not isinstance(complete, str) or not complete:
        if not isinstance(user_code, str) or not user_code:
            raise QrLoginFailed()
        complete = "https://i.xunlei.com/center/account/personal/qrcode-login/?user_code=" + quote(user_code, safe="")
    return StartedQr(device_code, device_id, _qr_png(_scan_url(complete)), "image/png")


def poll_qr(client: httpx.Client, device_code: str, device_id: str) -> PolledQr:
    response = _post(
        client,
        f"{AUTH}/auth/token",
        device_id,
        {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device_code,
        },
    )
    try:
        payload = response.json()
    except Exception as exc:
        raise QrLoginFailed() from exc
    if not isinstance(payload, dict):
        raise QrLoginFailed()
    error = payload.get("error")
    if error in {"authorization_pending", "slow_down"}:
        return PolledQr("waiting")
    if error in {"expired_token", "access_denied"}:
        return PolledQr("expired")
    access = payload.get("access_token")
    refresh = payload.get("refresh_token")
    user_id = payload.get("user_id") or payload.get("sub")
    if response.status_code >= 400 or not isinstance(access, str) or not isinstance(refresh, str) or not isinstance(user_id, str):
        raise QrLoginFailed()
    credential = {
        "access_token": access,
        "captcha_token": "",
        "client_id": CLIENT_ID,
        "device_id": device_id,
        "refresh_token": refresh,
        "user_id": user_id,
    }
    expires_in = payload.get("expires_in")
    if isinstance(expires_in, (int, float)) and expires_in > 0:
        credential["expires_at"] = int(time.time()) + int(expires_in)
    cookie = json.dumps(credential, separators=(",", ":"), sort_keys=True)
    return PolledQr("ready", cookie, None)
