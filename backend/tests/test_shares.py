import json
from datetime import timedelta
from urllib.parse import parse_qs

import httpx
from sqlalchemy import select

from app.core.crypto import encrypt_cookie
from app.models import DailyUsage, Job, PanAccount, ShareLink, User
from app.services.shares import execute_share
from app.services.transfers import EXPIRED
from tests.test_transfers import COOKIE, KEY, NOW

TARGETS = [
    {"fs_id": 11, "path": "/说明.txt", "name": "说明.txt"},
    {"fs_id": 12, "path": "/海报.jpg", "name": "海报.jpg"},
]


def register(client, email="share@example.com"):
    response = client.post("/api/auth/register", json={"email": email, "password": "password-123"})
    assert response.status_code == 201


def bind_and_pay(client, email="share@example.com"):
    register(client, email)
    with client.app.state.session_factory() as session:
        user = session.scalars(select(User).where(User.email == email)).one()
        user.plan = "paid"
        user.plan_expires_at = NOW + timedelta(days=30)
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


def install(client, handler):
    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))


def token_then(share_payloads):
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        assert COOKIE not in url
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        if "share/set" in url:
            form = parse_qs(request.content.decode())
            payload = share_payloads[state["n"]]
            state["n"] += 1
            assert form["period"] == [payload.get("period", "0")]
            assert len(form["pwd"][0]) == 4
            return httpx.Response(200, json=payload["body"])
        raise AssertionError(url)

    return handler


def test_free_user_cannot_create_a_share_job(client):
    register(client)
    with client.app.state.session_factory() as session:
        user = session.scalars(select(User).where(User.email == "share@example.com")).one()
        account = PanAccount(
            user_id=user.id,
            provider="baidu",
            nickname="网盘昵称",
            cookie_ciphertext=encrypt_cookie(COOKIE, KEY),
            status="valid",
        )
        session.add(account)
        session.commit()
        account_id = account.id
    response = client.post("/api/shares", json={"account_id": account_id, "directory": "/", "targets": TARGETS})
    assert response.status_code == 403
    assert response.json()["detail"] == "该功能仅对付费会员开放"
    with client.app.state.session_factory() as session:
        assert session.scalars(select(Job)).all() == []


def test_share_job_saves_links_and_exports_csv(client):
    account_id = bind_and_pay(client)
    install(client, token_then([
        {"period": "7", "body": {"errno": 0, "link": "https://pan.baidu.com/s/1aaaa"}},
        {"period": "7", "body": {"errno": 2}},
    ]))
    created = client.post("/api/shares", json={
        "account_id": account_id,
        "directory": "/",
        "period": 7,
        "password": "ab12",
        "targets": TARGETS,
    })
    assert created.status_code == 201
    assert COOKIE not in created.text
    job_id = created.json()["id"]
    with client.app.state.session_factory() as session:
        job = session.get(Job, job_id)
        execute_share(session, client.app.state.pan_http_client, job, sleeper=lambda _seconds: None, now=NOW)
        session.commit()
    shown = client.get(f"/api/jobs/{job_id}")
    assert shown.json()["status"] == "partial"
    assert shown.json()["type"] == "share"
    exported = client.get(f"/api/jobs/{job_id}/export")
    assert exported.status_code == 200
    text = exported.content.decode("utf-8")
    assert text.startswith("\ufeff名称,路径,分享链接,提取码,创建时间\r\n")
    assert "说明.txt,/" in text or "说明.txt,/说明.txt" in text
    assert "https://pan.baidu.com/s/1aaaa?pwd=ab12" in text
    assert "海报.jpg" not in text
    with client.app.state.session_factory() as session:
        link = session.scalars(select(ShareLink)).one()
        assert link.password == "ab12"
        assert link.baidu_share_id == "aaaa"
        usage = session.scalars(select(DailyUsage)).one()
        assert usage.share_count == 2


def test_expired_cookie_stops_remaining_shares(client):
    account_id = bind_and_pay(client)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "gettemplatevariable" in str(request.url):
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        if "share/set" in str(request.url):
            calls["n"] += 1
            return httpx.Response(200, json={"errno": -6})
        raise AssertionError(request.url)

    install(client, handler)
    created = client.post("/api/shares", json={"account_id": account_id, "directory": "/", "targets": TARGETS})
    job_id = created.json()["id"]
    with client.app.state.session_factory() as session:
        job = session.get(Job, job_id)
        execute_share(session, client.app.state.pan_http_client, job, sleeper=lambda _seconds: None, now=NOW)
        session.commit()
        account = session.get(PanAccount, account_id)
        assert account.status == "expired"
    shown = client.get(f"/api/jobs/{job_id}")
    errors = [item["error"] for item in shown.json()["items"]]
    assert errors == ["登录已失效，请重新登录", EXPIRED]
    assert calls["n"] == 1
    assert json.loads(shown.text)
