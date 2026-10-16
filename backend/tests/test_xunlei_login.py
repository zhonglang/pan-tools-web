import json

import httpx
from sqlalchemy import select

from datetime import datetime, timezone

from app.core.crypto import decrypt_cookie, encrypt_cookie
from app.models import PanAccount
from app.pans.xunlei import CLIENT_ID, CLIENT_SECRET
from app.pans.xunlei_login import _qr_png, _scan_url

KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


def test_old_device_verification_url_opens_the_login_page():
    legacy = f"https://xluser-ssl.xunlei.com/__/auth/device/?client_id={CLIENT_ID}&user_code=ABCD"
    assert _scan_url(legacy) == f"https://i.xunlei.com/center/account/personal/qrcode-login/?client_id={CLIENT_ID}&user_code=ABCD"


def test_xunlei_qr_confirm_saves_the_token_without_echoing_it(client):
    registered = client.post("/api/auth/register", json={"email": "xunlei-qr@example.com", "password": "password-123"})
    assert registered.status_code == 201

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/auth/device/code"):
            body = json.loads(request.content)
            assert body["client_id"] == CLIENT_ID
            assert body["scope"] == "profile offline pan sso user"
            assert request.headers["x-client-id"] == CLIENT_ID
            return httpx.Response(
                200,
                json={
                    "device_code": "device-code-1",
                    "user_code": "ABCD",
                    "verification_uri_complete": (
                        "https://xluser-ssl.xunlei.com/__/auth/device/"
                        f"?client_id={CLIENT_ID}&scope=profile%20offline%20pan%20sso%20user&user_code=ABCD"
                    ),
                },
            )
        if path.endswith("/auth/token"):
            body = json.loads(request.content)
            assert body["grant_type"] == "urn:ietf:params:oauth:grant-type:device_code"
            assert body["device_code"] == "device-code-1"
            assert body["client_id"] == CLIENT_ID
            assert body["client_secret"] == CLIENT_SECRET
            return httpx.Response(200, json={"access_token": "access-1", "refresh_token": "refresh-1", "user_id": "user-1"})
        if path.endswith("/captcha/init"):
            body = json.loads(request.content)
            assert body["client_id"] == CLIENT_ID
            assert body["meta"]["captcha_sign"].startswith("1.")
            return httpx.Response(200, json={"captcha_token": "cap-1"})
        if path.endswith("/user/me"):
            assert request.headers["authorization"] == "Bearer access-1"
            assert request.headers["x-client-id"] == CLIENT_ID
            return httpx.Response(200, json={"name": "迅雷昵称"})
        raise AssertionError(path)

    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))
    started = client.post("/api/accounts/xunlei/login", json={})
    assert started.status_code == 201
    session_id = started.json()["id"]
    image = client.get(f"/api/accounts/xunlei/login/{session_id}/qrcode")
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")
    scan_url = (
        "https://i.xunlei.com/center/account/personal/qrcode-login/"
        f"?client_id={CLIENT_ID}&scope=profile%20offline%20pan%20sso%20user&user_code=ABCD"
    )
    assert image.content == _qr_png(scan_url)
    ready = client.get(f"/api/accounts/xunlei/login/{session_id}")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["nickname"] == "迅雷昵称"
    assert "access-1" not in ready.text
    confirmed = client.post(f"/api/accounts/xunlei/login/{session_id}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["provider"] == "xunlei"
    assert "access-1" not in confirmed.text
    assert "refresh-1" not in confirmed.text
    with client.app.state.session_factory() as session:
        saved = session.scalars(select(PanAccount)).one()
        cookie = json.loads(decrypt_cookie(saved.cookie_ciphertext, KEY))
        assert cookie["access_token"] == "access-1"
        assert cookie["refresh_token"] == "refresh-1"
        assert cookie["client_id"] == CLIENT_ID
        assert saved.nickname == "迅雷昵称"


def _xunlei_login_handler(user_id: str):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/auth/device/code"):
            return httpx.Response(
                200,
                json={
                    "device_code": "device-code-1",
                    "user_code": "ABCD",
                    "verification_uri_complete": (
                        "https://xluser-ssl.xunlei.com/__/auth/device/"
                        f"?client_id={CLIENT_ID}&user_code=ABCD"
                    ),
                },
            )
        if path.endswith("/auth/token"):
            return httpx.Response(
                200,
                json={"access_token": "access-new", "refresh_token": "refresh-new", "user_id": user_id},
            )
        if path.endswith("/captcha/init"):
            return httpx.Response(200, json={"captcha_token": "cap-1"})
        if path.endswith("/user/me"):
            return httpx.Response(200, json={"name": "迅雷昵称"})
        raise AssertionError(path)

    return handler


def _confirm_xunlei(client, user_id: str) -> dict:
    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(_xunlei_login_handler(user_id)))
    started = client.post("/api/accounts/xunlei/login", json={})
    assert started.status_code == 201
    session_id = started.json()["id"]
    ready = client.get(f"/api/accounts/xunlei/login/{session_id}")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    confirmed = client.post(f"/api/accounts/xunlei/login/{session_id}/confirm")
    assert confirmed.status_code == 200
    return confirmed.json()


def test_xunlei_rescan_updates_the_expired_account(client):
    registered = client.post("/api/auth/register", json={"email": "xunlei-again@example.com", "password": "password-123"})
    assert registered.status_code == 201
    old = json.dumps(
        {
            "access_token": "access-old",
            "captcha_token": "",
            "client_id": CLIENT_ID,
            "device_id": "device-old",
            "refresh_token": "refresh-old",
            "user_id": "user-1",
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    now = datetime.now(timezone.utc)
    with client.app.state.session_factory() as session:
        account = PanAccount(
            user_id=registered.json()["id"],
            provider="xunlei",
            nickname="原来的迅雷",
            cookie_ciphertext=encrypt_cookie(old, KEY),
            status="expired",
            created_at=now,
            updated_at=now,
        )
        session.add(account)
        session.commit()
        original_id = account.id

    confirmed = _confirm_xunlei(client, "user-1")
    assert confirmed["id"] == original_id
    assert confirmed["status"] == "valid"
    with client.app.state.session_factory() as session:
        rows = list(session.scalars(select(PanAccount)))
        assert len(rows) == 1
        assert rows[0].id == original_id
        assert rows[0].status == "valid"
        cookie = json.loads(decrypt_cookie(rows[0].cookie_ciphertext, KEY))
        assert cookie["refresh_token"] == "refresh-new"
        assert cookie["user_id"] == "user-1"


def test_xunlei_rescan_keeps_the_used_account_and_drops_the_empty_duplicate(client):
    registered = client.post("/api/auth/register", json={"email": "xunlei-dup@example.com", "password": "password-123"})
    assert registered.status_code == 201
    cookie = json.dumps({"access_token": "access-old", "refresh_token": "refresh-old", "user_id": "user-1"}, separators=(",", ":"))
    earlier = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)
    later = datetime(2026, 10, 10, 11, 0, tzinfo=timezone.utc)
    with client.app.state.session_factory() as session:
        session.add(
            PanAccount(
                user_id=registered.json()["id"],
                provider="xunlei",
                nickname="空的迅雷",
                cookie_ciphertext=encrypt_cookie(cookie, KEY),
                status="expired",
                created_at=earlier,
                updated_at=earlier,
            )
        )
        used = PanAccount(
            user_id=registered.json()["id"],
            provider="xunlei",
            nickname="正在用的迅雷",
            cookie_ciphertext=encrypt_cookie(cookie, KEY),
            status="expired",
            created_at=later,
            updated_at=later,
        )
        session.add(used)
        session.commit()
        used_id = used.id

    confirmed = _confirm_xunlei(client, "user-1")
    assert confirmed["id"] == used_id
    assert confirmed["status"] == "valid"
    with client.app.state.session_factory() as session:
        rows = list(session.scalars(select(PanAccount)))
        assert [row.id for row in rows] == [used_id]
        assert rows[0].status == "valid"


def test_list_files_persists_rotated_xunlei_tokens(client):
    registered = client.post("/api/auth/register", json={"email": "xunlei-persist@example.com", "password": "password-123"})
    assert registered.status_code == 201
    cookie = json.dumps(
        {
            "access_token": "access-1",
            "captcha_token": "cap-1",
            "client_id": CLIENT_ID,
            "device_id": "a" * 32,
            "expires_at": 4102444800,
            "refresh_token": "refresh-1",
            "user_id": "user-1",
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    now = datetime.now(timezone.utc)
    with client.app.state.session_factory() as session:
        account = PanAccount(
            user_id=registered.json()["id"],
            provider="xunlei",
            nickname="迅雷",
            cookie_ciphertext=encrypt_cookie(cookie, KEY),
            status="valid",
            created_at=now,
            updated_at=now,
        )
        session.add(account)
        session.commit()
        account_id = account.id

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/files") and request.method == "GET":
            auth = request.headers.get("authorization")
            if auth == "Bearer access-1":
                return httpx.Response(401, json={"error_code": 16, "error": "unauthenticated"})
            assert auth == "Bearer access-2"
            return httpx.Response(200, json={"files": [], "next_page_token": ""})
        if path.endswith("/auth/token"):
            body = json.loads(request.content)
            assert body["refresh_token"] == "refresh-1"
            return httpx.Response(
                200,
                json={"access_token": "access-2", "refresh_token": "refresh-2", "expires_in": 7200},
            )
        if path.endswith("/captcha/init"):
            return httpx.Response(200, json={"captcha_token": "cap-2"})
        raise AssertionError(path)

    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))
    response = client.get(f"/api/accounts/{account_id}/files", params={"dir": "/"})
    assert response.status_code == 200
    with client.app.state.session_factory() as session:
        saved = session.get(PanAccount, account_id)
        stored = json.loads(decrypt_cookie(saved.cookie_ciphertext, KEY))
        assert stored["access_token"] == "access-2"
        assert stored["refresh_token"] == "refresh-2"
        assert stored["captcha_token"] == "cap-2"
        assert stored["expires_at"] >= int(datetime.now(timezone.utc).timestamp()) + 7000


def test_xunlei_rescan_of_a_different_user_creates_another_account(client):
    registered = client.post("/api/auth/register", json={"email": "xunlei-other@example.com", "password": "password-123"})
    assert registered.status_code == 201
    old = json.dumps({"access_token": "access-old", "refresh_token": "refresh-old", "user_id": "user-1"}, separators=(",", ":"))
    now = datetime.now(timezone.utc)
    with client.app.state.session_factory() as session:
        session.add(
            PanAccount(
                user_id=registered.json()["id"],
                provider="xunlei",
                nickname="原来的迅雷",
                cookie_ciphertext=encrypt_cookie(old, KEY),
                status="expired",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    confirmed = _confirm_xunlei(client, "user-2")
    assert confirmed["status"] == "valid"
    with client.app.state.session_factory() as session:
        rows = list(session.scalars(select(PanAccount).order_by(PanAccount.id)))
        assert [row.status for row in rows] == ["expired", "valid"]
        assert rows[1].id == confirmed["id"]
