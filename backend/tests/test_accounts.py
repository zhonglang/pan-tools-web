from datetime import datetime, timedelta, timezone

import httpx

from app.core.crypto import encrypt_cookie
from app.models import PanAccount

KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
SECRET = "BDUSS=super-secret-cookie-value"


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


def save_account(client, user_id: int, provider: str, nickname: str, status: str = "valid") -> int:
    with client.app.state.session_factory() as session:
        account = PanAccount(
            user_id=user_id,
            provider=provider,
            nickname=nickname,
            cookie_ciphertext=encrypt_cookie(SECRET, KEY),
            status=status,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(account)
        session.commit()
        session.refresh(account)
        return account.id


def test_paste_cookie_is_rejected(client):
    register(client)
    created = client.post("/api/accounts", json={"provider": "baidu", "cookie": SECRET})
    assert created.status_code == 422
    assert created.json()["detail"] == "请使用扫码登录"
    updated = client.patch("/api/accounts/1", json={"cookie": SECRET})
    assert updated.status_code == 422
    assert updated.json()["detail"] == "请使用扫码登录"
    assert client.get("/api/accounts").json() == []


def test_guest_cannot_list_accounts(client):
    response = client.get("/api/accounts")
    assert response.status_code == 401
    assert response.json()["detail"] == "未登录"


def test_free_user_can_keep_one_of_each_drive(client):
    user = register(client)
    save_account(client, user["id"], "baidu", "百度账号")
    save_account(client, user["id"], "quark", "夸克账号")
    save_account(client, user["id"], "xunlei", "迅雷账号")
    denied = client.post("/api/accounts/xunlei/login", json={})
    assert denied.status_code == 422
    assert denied.json()["detail"] == "免费用户只能绑定 1 个迅雷账号"
    providers = [row["provider"] for row in client.get("/api/accounts").json()]
    assert providers == ["baidu", "quark", "xunlei"]


def test_free_user_cannot_bind_a_second_valid_account(client):
    user = register(client)
    save_account(client, user["id"], "baidu", "第一个")
    again = client.post("/api/accounts/baidu/login", json={})
    assert again.status_code == 422
    assert again.json()["detail"] == "免费用户只能绑定 1 个百度账号"
    assert len(client.get("/api/accounts").json()) == 1


def test_expired_account_does_not_use_a_slot(client):
    user = register(client)
    save_account(client, user["id"], "baidu", "旧账号", status="expired")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getqrcode"):
            return httpx.Response(200, text='{"errno":0,"sign":"sign-1","imgurl":"https://passport.baidu.com/img.png"}')
        if request.url.path.endswith("/img.png"):
            return httpx.Response(200, content=b"png", headers={"content-type": "image/png"})
        raise AssertionError(str(request.url))

    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))
    again = client.post("/api/accounts/baidu/login", json={})
    assert again.status_code == 201


def test_paid_user_stops_at_five_accounts(client):
    user = register(client)
    grant_paid(client, user["id"])
    for index in range(5):
        save_account(client, user["id"], "baidu", f"账号{index}")
    denied = client.post("/api/accounts/baidu/login", json={})
    assert denied.status_code == 422
    assert denied.json()["detail"] == "最多绑定 5 个百度账号"
