from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.crypto import encrypt_cookie
from app.models import DailyUsage, Job, JobItem, PanAccount, User
from app.quota import shanghai_today
from app.transfers import execute_job, reclaim_stale

KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
COOKIE = "BDUSS=super-secret-cookie-value"
NOW = datetime(2026, 9, 22, 4, 0, tzinfo=timezone.utc)


def register(client, email="user@example.com"):
    response = client.post("/api/auth/register", json={"email": email, "password": "password-123"})
    assert response.status_code == 201
    return response


def bind(client, cookie=COOKIE):
    with client.app.state.session_factory() as session:
        user = session.scalars(select(User).where(User.email == "user@example.com")).one()
        account = PanAccount(
            user_id=user.id,
            provider="baidu",
            nickname="网盘昵称",
            cookie_ciphertext=encrypt_cookie(cookie, KEY),
            status="valid",
        )
        session.add(account)
        session.commit()
        return account.id


def install(client, handler):
    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))


def list_ok(request: httpx.Request) -> httpx.Response:
    if "xpan/file" in str(request.url):
        return httpx.Response(200, json={"errno": 0, "list": []})
    raise AssertionError(request.url)


def test_free_limit_does_not_create_a_job(client):
    register(client)
    account_id = bind(client)
    install(client, list_ok)
    with client.app.state.session_factory() as session:
        user = session.scalars(select(User).where(User.email == "user@example.com")).one()
        session.add(DailyUsage(user_id=user.id, usage_date=shanghai_today(NOW), transfer_count=100, share_count=0))
        session.commit()
    response = client.post("/api/transfers", json={
        "account_id": account_id,
        "directory": "/来自转存",
        "links": "https://pan.baidu.com/s/1AbCdEf ab12",
        "now": "2026-09-22T04:00:00+00:00",
    })
    assert response.status_code == 422
    assert response.json()["detail"] == "今日还可转存 0 条"
    assert COOKIE not in response.text
    with client.app.state.session_factory() as session:
        assert session.scalars(select(Job)).first() is None
        assert session.scalars(select(DailyUsage)).one().transfer_count == 100


def test_missing_directory_does_not_spend_quota(client):
    register(client)
    account_id = bind(client)

    def handler(request: httpx.Request) -> httpx.Response:
        assert "share/transfer" not in str(request.url)
        return httpx.Response(200, json={"errno": -9})

    install(client, handler)
    response = client.post("/api/transfers", json={
        "account_id": account_id,
        "directory": "/没有",
        "links": "https://pan.baidu.com/s/1AbCdEf",
    })
    assert response.status_code == 422
    assert response.json()["detail"] == "目标目录不存在"
    with client.app.state.session_factory() as session:
        assert session.scalars(select(Job)).first() is None
        assert session.scalars(select(DailyUsage)).first() is None


def test_job_runs_partial_and_hides_cookie(client):
    register(client)
    account_id = bind(client)
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        assert COOKIE not in url
        if "xpan/file" in url:
            return httpx.Response(200, json={"errno": 0, "list": []})
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        if "share/verify" in url:
            state["n"] += 1
            errno = 0 if state["n"] == 1 else -12
            return httpx.Response(200, json={"errno": errno, "randsk": "rand-sk"})
        if "share/list" in url:
            return httpx.Response(200, json={"errno": 0, "share_id": 9, "uk": 8, "list": [{"fs_id": 11}]})
        if "share/transfer" in url:
            return httpx.Response(200, json={"errno": 0})
        raise AssertionError(url)

    install(client, handler)
    created = client.post("/api/transfers", json={
        "account_id": account_id,
        "directory": "/来自转存",
        "links": "https://pan.baidu.com/s/1AbCdEf ab12\n\n不是链接\nhttps://pan.baidu.com/s/1ZzYyXx cd34",
    })
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "pending"
    assert COOKIE not in created.text
    job_id = body["id"]
    with client.app.state.session_factory() as session:
        job = session.get(Job, job_id)
        execute_job(session, client.app.state.pan_http_client, job, sleeper=lambda _seconds: None, now=NOW)
        session.commit()
    shown = client.get(f"/api/jobs/{job_id}")
    assert shown.status_code == 200
    assert shown.json()["status"] == "partial"
    reasons = [item["error"] for item in shown.json()["items"]]
    assert reasons == [None, "链接无法解析", "提取码错误"]
    assert shown.json()["items"][0]["result"] == "已转存"
    assert COOKIE not in shown.text


def test_expired_cookie_stops_later_items(client):
    register(client)
    account_id = bind(client)
    calls = {"transfer": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "xpan/file" in url:
            return httpx.Response(200, json={"errno": 0, "list": []})
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": -6})
        calls["transfer"] += 1
        raise AssertionError(url)

    install(client, handler)
    created = client.post("/api/transfers", json={
        "account_id": account_id,
        "directory": "/",
        "links": "https://pan.baidu.com/s/1AbCdEf\nhttps://pan.baidu.com/s/1ZzYyXx",
    })
    job_id = created.json()["id"]
    with client.app.state.session_factory() as session:
        execute_job(session, client.app.state.pan_http_client, session.get(Job, job_id), sleeper=lambda _seconds: None, now=NOW)
        session.commit()
        account = session.get(PanAccount, account_id)
        items = session.scalars(select(JobItem).where(JobItem.job_id == job_id).order_by(JobItem.id)).all()
        assert account.status == "expired"
        assert [item.error for item in items] == ["登录已失效，请重新登录", "登录已失效，请重新登录"]
        assert calls["transfer"] == 0


def test_rate_limit_retries_then_succeeds(client):
    register(client)
    account_id = bind(client)
    waits = []
    verify_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "xpan/file" in url:
            return httpx.Response(200, json={"errno": 0, "list": []})
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        if "share/verify" in url:
            verify_calls["n"] += 1
            errno = 31034 if verify_calls["n"] < 3 else 0
            return httpx.Response(200, json={"errno": errno, "randsk": "rand-sk"})
        if "share/list" in url:
            return httpx.Response(200, json={"errno": 0, "share_id": 9, "uk": 8, "list": [{"fs_id": 11}]})
        if "share/transfer" in url:
            return httpx.Response(200, json={"errno": 0})
        raise AssertionError(url)

    install(client, handler)
    created = client.post("/api/transfers", json={
        "account_id": account_id,
        "directory": "/",
        "links": "https://pan.baidu.com/s/1AbCdEf",
    })
    job_id = created.json()["id"]
    with client.app.state.session_factory() as session:
        execute_job(
            session,
            client.app.state.pan_http_client,
            session.get(Job, job_id),
            sleeper=waits.append,
            now=NOW,
        )
        session.commit()
        item = session.scalars(select(JobItem)).one()
        assert waits == [2, 8]
        assert item.attempts == 3
        assert item.status == "succeeded"


def test_stale_running_item_is_requeued_until_attempt_cap(client):
    register(client)
    account_id = bind(client)
    old = NOW - timedelta(minutes=16)
    with client.app.state.session_factory() as session:
        user = session.scalars(select(User).where(User.email == "user@example.com")).one()
        job = Job(user_id=user.id, account_id=account_id, type="transfer", directory="/", status="running", updated_at=old)
        session.add(job)
        session.flush()
        session.add(JobItem(job_id=job.id, input_text="https://pan.baidu.com/s/1AbCdEf", status="running", attempts=1, updated_at=old))
        session.add(JobItem(job_id=job.id, input_text="https://pan.baidu.com/s/1ZzYyXx", status="running", attempts=3, updated_at=old))
        session.commit()
        job_id = job.id
    with client.app.state.session_factory() as session:
        reclaim_stale(session, NOW)
        session.commit()
        items = session.scalars(select(JobItem).where(JobItem.job_id == job_id).order_by(JobItem.id)).all()
        assert items[0].status == "pending"
        assert items[1].status == "failed"
        assert items[1].error == "已达到重试上限"
        assert session.get(Job, job_id).status == "pending"
