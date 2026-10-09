import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.core.crypto import decrypt_cookie
from app.models import PanAccount

KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
SECRET = "BDUSS=super-secret-cookie-value"


def install_baidu(client, payload=None, status_code=200, text=None, calls=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request.headers.get("cookie"))
        if text is not None:
            return httpx.Response(status_code, text=text)
        return httpx.Response(status_code, json=payload)

    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))


def register(client, email="user@example.com"):
    response = client.post("/api/auth/register", json={"email": email, "password": "password-123"})
    assert response.status_code == 201
    return response.json()


def grant_paid(client, user_id: int):
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "admin@example.com", "password": "admin-pass-123"})
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    updated = client.patch(
        f"/api/admin/users/{user_id}",
        json={"plan": "paid", "plan_expires_at": future},
    )
    assert updated.status_code == 200
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "user@example.com", "password": "password-123"})


def test_bind_stores_ciphertext_and_hides_cookie(client, caplog):
    caplog.set_level(logging.DEBUG, logger="app")
    register(client)
    install_baidu(client, {"errno": 0, "netdisk_name": "网盘昵称", "baidu_name": "百度名"})
    response = client.post("/api/accounts", json={"provider": "baidu", "cookie": f"  {SECRET}  "})
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "provider", "nickname", "status", "created_at", "updated_at"}
    assert body["provider"] == "baidu"
    assert body["nickname"] == "网盘昵称"
    assert body["status"] == "valid"
    assert SECRET not in response.text
    assert SECRET not in caplog.text

    listed = client.get("/api/accounts")
    assert listed.status_code == 200
    assert SECRET not in listed.text
    assert listed.json()[0]["nickname"] == "网盘昵称"

    with client.app.state.session_factory() as session:
        saved = session.scalars(select(PanAccount)).one()
        assert saved.cookie_ciphertext != SECRET
        assert decrypt_cookie(saved.cookie_ciphertext, KEY) == SECRET


def test_bind_rejects_failed_check_without_saving(client):
    register(client)
    install_baidu(client, {"errno": -6})
    response = client.post("/api/accounts", json={"provider": "baidu", "cookie": SECRET})
    assert response.status_code == 422
    assert response.json()["detail"] == "请重新登录百度后再粘贴 Cookie"
    assert client.get("/api/accounts").json() == []


def test_bind_rejects_blank_cookie(client):
    register(client)
    response = client.post("/api/accounts", json={"provider": "baidu", "cookie": "   "})
    assert response.status_code == 422
    assert response.json()["detail"] == "Cookie 不能为空"


def test_quark_and_xunlei_are_closed(client):
    register(client)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("closed provider must not send HTTP")

    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))
    for provider in ("quark", "xunlei"):
        response = client.post("/api/accounts", json={"provider": provider, "cookie": SECRET})
        assert response.status_code == 422
        assert response.json()["detail"] == "暂未开放"
    assert client.get("/api/accounts").json() == []


def test_unknown_provider_is_rejected(client):
    register(client)
    response = client.post("/api/accounts", json={"provider": "dropbox", "cookie": SECRET})
    assert response.status_code == 422
    assert response.json()["detail"] == "网盘类型无效"


def test_guest_cannot_list_accounts(client):
    response = client.get("/api/accounts")
    assert response.status_code == 401
    assert response.json()["detail"] == "未登录"


def test_free_user_cannot_bind_a_second_valid_account(client):
    register(client)
    install_baidu(client, {"errno": 0, "netdisk_name": "第一个"})
    assert client.post("/api/accounts", json={"provider": "baidu", "cookie": SECRET}).status_code == 201
    install_baidu(client, {"errno": 0, "netdisk_name": "第二个"})
    again = client.post("/api/accounts", json={"provider": "baidu", "cookie": "BDUSS=another-secret"})
    assert again.status_code == 422
    assert again.json()["detail"] == "免费用户只能绑定 1 个百度账号"
    assert len(client.get("/api/accounts").json()) == 1


def test_expired_account_does_not_use_a_slot(client):
    register(client)
    install_baidu(client, {"errno": 0, "netdisk_name": "旧账号"})
    created = client.post("/api/accounts", json={"provider": "baidu", "cookie": SECRET})
    with client.app.state.session_factory() as session:
        account = session.get(PanAccount, created.json()["id"])
        account.status = "expired"
        session.commit()
    install_baidu(client, {"errno": 0, "netdisk_name": "新账号"})
    again = client.post("/api/accounts", json={"provider": "baidu", "cookie": "BDUSS=another-secret"})
    assert again.status_code == 201
    assert again.json()["nickname"] == "新账号"


def test_paid_user_stops_at_five_accounts(client):
    user = register(client)
    grant_paid(client, user["id"])
    for index in range(5):
        install_baidu(client, {"errno": 0, "netdisk_name": f"账号{index}"})
        response = client.post("/api/accounts", json={"provider": "baidu", "cookie": f"BDUSS=secret-{index}"})
        assert response.status_code == 201
    install_baidu(client, {"errno": 0, "netdisk_name": "第六个"})
    denied = client.post("/api/accounts", json={"provider": "baidu", "cookie": "BDUSS=secret-6"})
    assert denied.status_code == 422
    assert denied.json()["detail"] == "最多绑定 5 个百度账号"


def test_update_cookie_replaces_ciphertext(client):
    register(client)
    install_baidu(client, {"errno": 0, "netdisk_name": "旧昵称"})
    created = client.post("/api/accounts", json={"provider": "baidu", "cookie": SECRET})
    account_id = created.json()["id"]
    install_baidu(client, {"errno": 0, "netdisk_name": "新昵称"})
    updated = client.patch(f"/api/accounts/{account_id}", json={"cookie": "BDUSS=replacement-secret"})
    assert updated.status_code == 200
    assert updated.json()["nickname"] == "新昵称"
    assert updated.json()["status"] == "valid"
    assert "replacement-secret" not in updated.text
    with client.app.state.session_factory() as session:
        saved = session.get(PanAccount, account_id)
        assert decrypt_cookie(saved.cookie_ciphertext, KEY) == "BDUSS=replacement-secret"


def test_update_keeps_the_row_when_check_fails(client):
    register(client)
    install_baidu(client, {"errno": 0, "netdisk_name": "旧昵称"})
    created = client.post("/api/accounts", json={"provider": "baidu", "cookie": SECRET})
    account_id = created.json()["id"]
    install_baidu(client, {"errno": -6})
    failed = client.patch(f"/api/accounts/{account_id}", json={"cookie": "BDUSS=bad-secret"})
    assert failed.status_code == 422
    with client.app.state.session_factory() as session:
        saved = session.get(PanAccount, account_id)
        assert saved.nickname == "旧昵称"
        assert decrypt_cookie(saved.cookie_ciphertext, KEY) == SECRET


def test_update_of_valid_account_does_not_require_another_slot(client):
    register(client)
    install_baidu(client, {"errno": 0, "netdisk_name": "唯一"})
    created = client.post("/api/accounts", json={"provider": "baidu", "cookie": SECRET})
    install_baidu(client, {"errno": 0, "netdisk_name": "换过"})
    updated = client.patch(f"/api/accounts/{created.json()['id']}", json={"cookie": "BDUSS=replacement-secret"})
    assert updated.status_code == 200
    assert len(client.get("/api/accounts").json()) == 1


def test_cannot_update_someone_elses_account(client):
    register(client, "user@example.com")
    install_baidu(client, {"errno": 0, "netdisk_name": "用户的"})
    created = client.post("/api/accounts", json={"provider": "baidu", "cookie": SECRET})
    client.post("/api/auth/logout")
    register(client, "other@example.com")
    install_baidu(client, {"errno": 0, "netdisk_name": "不该发生"})
    response = client.patch(f"/api/accounts/{created.json()['id']}", json={"cookie": "BDUSS=other-secret"})
    assert response.status_code == 404
    assert response.json()["detail"] == "账号不存在"


def test_missing_account_is_not_found(client):
    register(client)
    response = client.patch("/api/accounts/999", json={"cookie": SECRET})
    assert response.status_code == 404
    assert response.json()["detail"] == "账号不存在"
