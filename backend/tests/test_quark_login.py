import httpx
from sqlalchemy import select

from app.core.crypto import decrypt_cookie
from app.models import PanAccount

KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
PNG = b"\x89PNG\r\n\x1a\n"


def test_quark_qr_confirm_saves_cookie_without_echoing_it(client):
    registered = client.post("/api/auth/register", json={"email": "quark-qr@example.com", "password": "password-123"})
    assert registered.status_code == 201

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/getTokenForQrcodeLogin"):
            return httpx.Response(200, json={"status": 2000000, "data": {"token": "qr-token"}})
        if request.url.host == "su.quark.cn":
            assert request.url.params["token"] == "qr-token"
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
        if path.endswith("/getServiceTicketByQrcodeToken"):
            return httpx.Response(200, json={"status": 2000000, "data": {"service_ticket": "st-1", "status": 2}})
        if path.endswith("/loginWithServiceTicket"):
            assert request.url.params["st"] == "st-1"
            return httpx.Response(200, headers={"set-cookie": "__puus=secret; Path=/"})
        if path.endswith("/member"):
            assert "__puus=secret" in request.headers["cookie"]
            return httpx.Response(200, json={"status": 200, "data": {"nickname": "扫码夸克"}})
        raise AssertionError(str(request.url))

    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))
    started = client.post("/api/accounts/quark/login", json={})
    assert started.status_code == 201
    assert "secret" not in started.text
    session_id = started.json()["id"]
    ready = client.get(f"/api/accounts/quark/login/{session_id}")
    assert ready.status_code == 200
    assert ready.json()["nickname"] == "扫码夸克"
    assert "secret" not in ready.text
    confirmed = client.post(f"/api/accounts/quark/login/{session_id}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["provider"] == "quark"
    assert confirmed.json()["nickname"] == "扫码夸克"
    assert "secret" not in confirmed.text
    with client.app.state.session_factory() as session:
        saved = session.scalars(select(PanAccount)).one()
        assert saved.provider == "quark"
        assert "__puus=secret" in decrypt_cookie(saved.cookie_ciphertext, KEY)
