import json
from urllib.parse import parse_qs

import httpx
from sqlalchemy import select

from app.core.crypto import encrypt_cookie
from app.models import PanAccount, User

KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
COOKIE = "BDUSS=super-secret-cookie-value"


def register(client, email="copy@example.com"):
    response = client.post("/api/auth/register", json={"email": email, "password": "password-123"})
    assert response.status_code == 201
    return response


def bind(client, email="copy@example.com"):
    with client.app.state.session_factory() as session:
        user = session.scalars(select(User).where(User.email == email)).one()
        account = PanAccount(
            user_id=user.id,
            provider="baidu",
            nickname="网盘昵称",
            cookie_ciphertext=encrypt_cookie(COOKIE, KEY),
            status="valid",
        )
        session.add(account)
        session.commit()
        return account.id


def test_copy_to_sibling_folders_renames_on_duplicate(client):
    register(client)
    account_id = bind(client)
    copies = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        if "filemanager" in url and request.url.params["opera"] == "copy":
            form = parse_qs(request.content.decode())
            item = json.loads(form["filelist"][0])[0]
            copies.append(item)
            if item["dest"] == "/父/B" and item["newname"] == "源":
                return httpx.Response(200, json={"errno": -33})
            return httpx.Response(200, json={"errno": 0})
        raise AssertionError(url)

    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))
    response = client.post(
        f"/api/accounts/{account_id}/files/copy",
        json={
            "path": "/父/源",
            "fs_id": None,
            "name": "源",
            "is_dir": True,
            "targets": ["/父/A", "/父/B"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["succeeded"] == 2
    assert body["failed"] == 0
    assert body["results"][0]["name"] == "源"
    assert body["results"][1]["name"] == "源(1)"
    assert copies == [
        {"path": "/父/源", "dest": "/父/A", "newname": "源"},
        {"path": "/父/源", "dest": "/父/B", "newname": "源"},
        {"path": "/父/源", "dest": "/父/B", "newname": "源(1)"},
    ]


def test_copy_rejects_cross_parent_targets(client):
    register(client, email="copy-cross@example.com")
    account_id = bind(client, email="copy-cross@example.com")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(request.url)

    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))
    response = client.post(
        f"/api/accounts/{account_id}/files/copy",
        json={"path": "/源", "name": "源", "is_dir": True, "targets": ["/a/1", "/b/2"]},
    )
    assert response.status_code == 422
    assert "同级" in response.json()["detail"]


def test_copy_rejects_self_target(client):
    register(client, email="copy-self@example.com")
    account_id = bind(client, email="copy-self@example.com")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(request.url)

    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))
    response = client.post(
        f"/api/accounts/{account_id}/files/copy",
        json={"path": "/父/源", "name": "源", "is_dir": True, "targets": ["/父/源"]},
    )
    assert response.status_code == 422
    assert "自身" in response.json()["detail"]
