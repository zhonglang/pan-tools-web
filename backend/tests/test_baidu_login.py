import json

import httpx
from sqlalchemy import select

from app.core.crypto import decrypt_cookie
from app.models import PanAccount

KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
SECRET = "super-secret-cookie-value"


def install_passport(client):
    unicast_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/getqrcode"):
            assert request.url.params["tpl"] == "netdisk"
            assert "loginv5" in request.url.params["logPage"]
            return httpx.Response(
                200,
                json={"errno": 0, "sign": "sign-1", "imgurl": "passport.baidu.com/v2/api/qrcode?sign=sign-1"},
            )
        if path.endswith("/qrcode"):
            assert request.url.params["sign"] == "sign-1"
            return httpx.Response(200, content=b"GIF89a", headers={"content-type": "image/gif"})
        if path.endswith("/unicast"):
            unicast_calls["n"] += 1
            if unicast_calls["n"] == 1:
                return httpx.Response(200, json={"errno": 1})
            if unicast_calls["n"] == 2:
                return httpx.Response(200, json={"errno": 0, "channel_v": json.dumps({"status": 1})})
            return httpx.Response(
                200,
                text='cb({"errno":0,"channel_v":"{\\"status\\":0,\\"v\\":\\"temp-token\\"}"})',
            )
        if path.endswith("/qrbdusslogin"):
            assert request.url.params["bduss"] == "temp-token"
            return httpx.Response(200, headers={"set-cookie": f"BDUSS={SECRET}; Path=/"})
        if request.url.params.get("method") == "uinfo":
            assert SECRET in request.headers["cookie"]
            return httpx.Response(200, json={"errno": 0, "netdisk_name": "扫码昵称", "baidu_name": "百度名"})
        raise AssertionError(f"unexpected request {request.url}")

    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))


def register(client):
    response = client.post("/api/auth/register", json={"email": "user@example.com", "password": "password-123"})
    assert response.status_code == 201


def test_qr_login_confirms_without_showing_cookie(client):
    register(client)
    install_passport(client)
    started = client.post("/api/accounts/baidu/login", json={})
    assert started.status_code == 201
    body = started.json()
    assert body["status"] == "waiting"
    assert SECRET not in started.text
    session_id = body["id"]

    image = client.get(f"/api/accounts/baidu/login/{session_id}/qrcode")
    assert image.status_code == 200
    assert image.content.startswith(b"GIF89a")
    assert SECRET not in image.content.decode("latin1")

    waiting = client.get(f"/api/accounts/baidu/login/{session_id}")
    assert waiting.status_code == 200
    assert waiting.json()["status"] == "waiting"

    scanned = client.get(f"/api/accounts/baidu/login/{session_id}")
    assert scanned.json()["status"] == "scanned"
    assert scanned.json()["nickname"] is None

    too_early = client.post(f"/api/accounts/baidu/login/{session_id}/confirm")
    assert too_early.status_code == 422
    assert too_early.json()["detail"] == "请先在手机上确认登录"

    ready = client.get(f"/api/accounts/baidu/login/{session_id}")
    assert ready.status_code == 200
    assert ready.json() == {"id": session_id, "status": "ready", "nickname": "扫码昵称"}
    assert SECRET not in ready.text

    confirmed = client.post(f"/api/accounts/baidu/login/{session_id}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["nickname"] == "扫码昵称"
    assert confirmed.json()["provider"] == "baidu"
    assert SECRET not in confirmed.text

    with client.app.state.session_factory() as session:
        saved = session.scalars(select(PanAccount)).one()
        assert decrypt_cookie(saved.cookie_ciphertext, KEY) == f"BDUSS={SECRET}"


def test_guest_cannot_start_baidu_login(client):
    response = client.post("/api/accounts/baidu/login", json={})
    assert response.status_code == 401
    assert response.json()["detail"] == "未登录"
