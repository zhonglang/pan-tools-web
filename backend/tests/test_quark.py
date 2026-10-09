import json
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.core.crypto import encrypt_cookie
from app.models import Job, JobItem, PanAccount, User
from app.pans import adapter_for
from app.pans.errors import WrongPassword
from app.services.transfers import execute_job

COOKIE = "b-user-id=1"
KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
NOW = datetime(2026, 9, 22, 4, 0, tzinfo=timezone.utc)


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_list_dir_maps_root_and_folder_type():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["pdir_fid"] == "0"
        return httpx.Response(
            200,
            json={
                "status": 200,
                "data": {
                    "list": [
                        {"fid": "folder-1", "file_name": "电影", "file_type": 0, "size": 0, "updated_at": 1700000000000},
                        {"fid": "file-1", "file_name": "a.mp4", "file_type": 1, "size": 12, "updated_at": 1700000000000},
                    ]
                },
            },
        )

    rows = adapter_for("quark", client_for(handler)).list_dir(COOKIE, "/")
    assert rows[0].name == "电影" and rows[0].is_dir and rows[0].path == "/folder-1"
    assert rows[1].name == "a.mp4" and rows[1].is_dir is False and rows[1].path == "/file-1"


def test_create_rename_delete_use_fid():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.read()))
        return httpx.Response(200, json={"status": 200, "data": {"fid": "new-1"}})

    adapter = adapter_for("quark", client_for(handler))
    created = adapter.create_dir(COOKIE, "/", "新文件夹")
    adapter.rename(COOKIE, "/folder-1", "新名字")
    adapter.delete(COOKIE, "/file-1")
    assert created.path == "/new-1"
    assert "/1/clouddrive/file/rename" in seen[1][1]
    assert b"file-1" in seen[2][2]


def test_transfer_share_saves_top_level_files():
    calls = {"task": 0}
    saved = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/share/sharepage/token"):
            return httpx.Response(200, json={"status": 200, "data": {"stoken": "st"}})
        if path.endswith("/share/sharepage/detail"):
            return httpx.Response(
                200,
                json={"status": 200, "data": {"list": [{"fid": "fid-1", "share_fid_token": "tok-1"}]}},
            )
        if path.endswith("/share/sharepage/save"):
            saved["body"] = json.loads(request.read())
            return httpx.Response(200, json={"status": 200, "data": {"task_id": "task-1"}})
        if path.endswith("/task"):
            calls["task"] += 1
            status = 1 if calls["task"] == 1 else 2
            return httpx.Response(200, json={"status": 200, "data": {"status": status}})
        raise AssertionError(path)

    adapter_for("quark", client_for(handler)).transfer_share(
        COOKIE,
        "https://pan.quark.cn/s/abc",
        "6666",
        "/folder-1",
        sleeper=lambda _seconds: None,
    )
    assert saved["body"]["to_pdir_fid"] == "folder-1"
    assert saved["body"]["fid_list"] == ["fid-1"]
    assert saved["body"]["pwd_id"] == "abc"


def test_quark_create_share_returns_url_and_password():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/share/password"):
            return httpx.Response(
                200,
                json={"status": 200, "data": {"share_url": "https://pan.quark.cn/s/share1", "passcode": "abcd"}},
            )
        if path.endswith("/task"):
            return httpx.Response(200, json={"status": 200, "data": {"status": 2, "share_id": "share-id"}})
        if path.endswith("/share"):
            return httpx.Response(200, json={"status": 200, "data": {"task_id": "task-1"}})
        raise AssertionError(path)

    url, password = adapter_for("quark", client_for(handler)).create_share(
        COOKIE,
        None,
        "wxyz",
        "0",
        path="/fid-1",
        name="电影",
        sleeper=lambda _seconds: None,
    )
    assert url == "https://pan.quark.cn/s/share1"
    assert password == "abcd"


def test_transfer_share_rejects_bad_password():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 400, "message": "提取码错误"})

    try:
        adapter_for("quark", client_for(handler)).transfer_share(COOKIE, "abc", "0000", "/")
    except WrongPassword:
        return
    raise AssertionError("expected WrongPassword")


def _account(client, provider: str) -> int:
    with client.app.state.session_factory() as session:
        user = session.scalars(select(User).where(User.email == "user@example.com")).one()
        account = PanAccount(
            user_id=user.id,
            provider=provider,
            nickname="昵称",
            cookie_ciphertext=encrypt_cookie(COOKIE, KEY),
            status="valid",
        )
        session.add(account)
        session.commit()
        return account.id


def test_transfer_job_names_the_required_provider(client):
    response = client.post("/api/auth/register", json={"email": "user@example.com", "password": "password-123"})
    assert response.status_code == 201
    baidu_id = _account(client, "baidu")
    created = client.post(
        "/api/transfers",
        json={
            "account_id": baidu_id,
            "directory": "/",
            "links": "https://pan.baidu.com/s/1AbCdEf\nhttps://pan.quark.cn/s/abc",
        },
    )
    assert created.status_code == 201
    assert [item["error"] for item in created.json()["items"]] == [None, "请使用夸克账号"]

    quark_id = _account(client, "quark")
    created = client.post(
        "/api/transfers",
        json={"account_id": quark_id, "directory": "/", "links": "https://pan.baidu.com/s/1AbCdEf"},
    )
    assert created.status_code == 201
    assert created.json()["items"][0]["error"] == "请使用百度账号"


def test_quark_login_rejected_marks_account_expired(client):
    response = client.post("/api/auth/register", json={"email": "user@example.com", "password": "password-123"})
    assert response.status_code == 201
    account_id = _account(client, "quark")
    created = client.post(
        "/api/transfers",
        json={
            "account_id": account_id,
            "directory": "/",
            "links": "https://pan.quark.cn/s/abc\nhttps://pan.quark.cn/s/def",
        },
    )
    job_id = created.json()["id"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 401, "message": "未登录"})

    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))
    with client.app.state.session_factory() as session:
        execute_job(session, client.app.state.pan_http_client, session.get(Job, job_id), sleeper=lambda _seconds: None, now=NOW)
        session.commit()
        account = session.get(PanAccount, account_id)
        items = session.scalars(select(JobItem).where(JobItem.job_id == job_id).order_by(JobItem.id)).all()
        assert account.status == "expired"
        assert [item.error for item in items] == ["登录已失效，请重新登录", "登录已失效，请重新登录"]
