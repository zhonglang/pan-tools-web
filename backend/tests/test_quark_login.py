import httpx
from sqlalchemy import select

from app.core.crypto import decrypt_cookie
from app.models import PanAccount
from app.pans.quark_login import qr_login_url

KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


def test_invalid_quark_ticket_expires_without_asking_for_a_cookie(client):
    registered = client.post("/api/auth/register", json={"email": "quark-invalid@example.com", "password": "password-123"})
    assert registered.status_code == 201

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/getTokenForQrcodeLogin"):
            return httpx.Response(200, json={"status": 2000000, "data": {"members": {"token": "qr-token"}}})
        if path.endswith("/getServiceTicketByQrcodeToken"):
            return httpx.Response(200, json={"status": 2000000, "data": {"members": {"service_ticket": "st-1"}}})
        if request.url.host == "pan.quark.cn" and path.endswith("/account/info"):
            return httpx.Response(
                200,
                headers={"set-cookie": "ctoken=not-a-login; Path=/"},
                json={"success": False, "code": "AUTH_ERROR:50051", "msg": "Invalid service ticket"},
            )
        raise AssertionError(str(request.url))

    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))
    started = client.post("/api/accounts/quark/login", json={})
    session_id = started.json()["id"]
    ready = client.get(f"/api/accounts/quark/login/{session_id}")
    assert ready.status_code == 200
    assert ready.json()["status"] == "expired"
    assert "粘贴 Cookie" not in ready.text


def test_quark_qr_url_keeps_the_token_through_the_app_redirect():
    url = qr_login_url("qr-token")
    assert url.startswith("https://su.quark.cn/4_eMHBJ?")
    assert "token=qr-token" in url
    assert "client_id=532" in url
    assert "ssb=weblogin" in url
    assert "uc_biz_str=S%3Acustom%7COPT%3ASAREA%400" in url


def test_quark_qr_confirm_saves_cookie_without_echoing_it(client):
    registered = client.post("/api/auth/register", json={"email": "quark-qr@example.com", "password": "password-123"})
    assert registered.status_code == 201

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/getTokenForQrcodeLogin"):
            assert request.url.params["client_id"] == "532"
            return httpx.Response(200, json={"status": 2000000, "data": {"members": {"token": "qr-token"}}})
        if path.endswith("/getServiceTicketByQrcodeToken"):
            assert request.url.params["token"] == "qr-token"
            return httpx.Response(
                200,
                json={"status": 2000000, "data": {"members": {"service_ticket": "st-1"}}},
            )
        if request.url.host == "pan.quark.cn" and path.endswith("/account/info"):
            assert request.url.params["st"] == "st-1"
            assert request.url.params["lw"] == "scan"
            return httpx.Response(
                302,
                headers=[
                    ("location", "https://pan.quark.cn/list/all"),
                    ("set-cookie", "__puus=secret; Domain=.quark.cn; Path=/; HttpOnly"),
                    ("set-cookie", "__pus=secret-pus; Domain=.quark.cn; Path=/; HttpOnly"),
                ],
            )
        if request.url.host == "pan.quark.cn" and path == "/list/all":
            return httpx.Response(
                200,
                headers={"set-cookie": "other=1; Path=/"},
                json={"success": True, "data": {"nickname": "扫码夸克"}},
            )
        if path.endswith("/member"):
            assert "__puus=secret" in request.headers["cookie"]
            return httpx.Response(200, json={"status": 200, "data": {"member_type": "NORMAL"}})
        raise AssertionError(str(request.url))

    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))
    started = client.post("/api/accounts/quark/login", json={})
    assert started.status_code == 201
    assert "secret" not in started.text
    assert "qr-token" not in started.text
    session_id = started.json()["id"]
    image = client.get(f"/api/accounts/quark/login/{session_id}/qrcode")
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")
    assert image.content.startswith(b"\x89PNG")
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
        saved_cookie = decrypt_cookie(saved.cookie_ciphertext, KEY)
        assert "__puus=secret" in saved_cookie
        assert "__pus=secret-pus" in saved_cookie
