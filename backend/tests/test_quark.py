import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app.core.crypto import encrypt_cookie
from app.models import Job, JobItem, PanAccount, ShareLink, ShareStatSnapshot, User
from app.pans import adapter_for
from app.pans.errors import DuplicateName, WrongPassword
from app.services.stats import enqueue_daily_syncs, execute_sync
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
                        {"fid": "folder-1", "file_name": "电影", "file_type": 0, "size": 0, "created_at": 1600000000000, "updated_at": 1700000000000},
                        {"fid": "file-1", "file_name": "a.mp4", "file_type": 1, "size": 12, "updated_at": 1700000000000},
                    ]
                },
            },
        )

    rows = adapter_for("quark", client_for(handler)).list_dir(COOKIE, "/")
    assert rows[0].name == "电影" and rows[0].is_dir and rows[0].path == "/folder-1"
    assert rows[0].created_at == 1600000000
    assert rows[0].modified_at == 1700000000
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


def test_open_download_streams_the_quark_file():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/file/download"):
            assert request.headers["cookie"] == COOKIE
            body = json.loads(request.read())
            assert body["fids"] == ["file-1"]
            return httpx.Response(200, json={"status": 200, "data": [{"download_url": "https://dl.example/a.bin"}]})
        assert request.url.host == "dl.example"
        return httpx.Response(200, content=b"hello", headers={"Content-Length": "5"})

    stream = adapter_for("quark", client_for(handler)).open_download(COOKIE, "/file-1")
    assert b"".join(stream) == b"hello"
    assert stream.size == 5


def test_list_share_records_keeps_missing_counts_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/share/mypage/detail")
        return httpx.Response(
            200,
            json={"status": 200, "data": {"list": [{"share_id": "s1", "pwd_id": "abc", "title": "电影"}]}},
        )

    records = adapter_for("quark", client_for(handler)).list_share_records(COOKIE)
    assert records[0]["views"] is None
    assert records[0]["transfers"] is None
    assert records[0]["downloads"] is None
    assert records[0]["url"].startswith("https://pan.quark.cn/s/")


def test_quark_share_job_accepts_files_inside_a_folder(client):
    response = client.post("/api/auth/register", json={"email": "quark-share@example.com", "password": "password-123"})
    assert response.status_code == 201
    with client.app.state.session_factory() as session:
        user = session.scalars(select(User).where(User.email == "quark-share@example.com")).one()
        user.plan = "paid"
        user.plan_expires_at = NOW + timedelta(days=30)
        account = PanAccount(
            user_id=user.id,
            provider="quark",
            nickname="夸克",
            cookie_ciphertext=encrypt_cookie(COOKIE, KEY),
            status="valid",
        )
        session.add(account)
        session.commit()
        account_id = account.id

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["pdir_fid"] == "folder-1"
        return httpx.Response(
            200,
            json={"status": 200, "data": {"list": [{"fid": "file-1", "file_name": "岗位表.xlsx", "file_type": 1}]}},
        )

    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))
    created = client.post(
        "/api/shares",
        json={
            "account_id": account_id,
            "directory": "/folder-1",
            "directory_label": "根目录 / 网盘拉新资源 / 岗位表",
            "targets": [{"fs_id": None, "path": "/file-1", "name": "岗位表.xlsx"}],
        },
    )
    assert created.status_code == 201
    assert created.json()["directory_label"] == "根目录 / 网盘拉新资源 / 岗位表"
    public = client.post(
        "/api/shares",
        json={
            "account_id": account_id,
            "directory": "/",
            "visibility": "public",
            "targets": [{"fs_id": None, "path": "/file-1", "name": "岗位表.xlsx"}],
        },
    )
    assert public.status_code == 201
    with client.app.state.session_factory() as session:
        item = session.scalars(select(JobItem).where(JobItem.job_id == public.json()["id"])).one()
        assert json.loads(item.input_text)["password"] == ""
    rejected = client.post(
        "/api/shares",
        json={
            "account_id": account_id,
            "directory": "/folder-1",
            "targets": [{"fs_id": None, "path": "/other-file", "name": "别的文件"}],
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "只能分享当前目录中的项目"


def test_quark_create_share_returns_url_and_password():
    seen: dict[str, object] = {}

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
            seen["body"] = json.loads(request.content)
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
    assert seen["body"] == {
        "fid_list": ["fid-1"],
        "title": "电影",
        "url_type": 2,
        "expired_type": 1,
        "passcode": "wxyz",
    }


def test_quark_row_share_creates_a_public_link_without_a_password(client):
    response = client.post("/api/auth/register", json={"email": "quark-row@example.com", "password": "password-123"})
    assert response.status_code == 201
    with client.app.state.session_factory() as session:
        user = session.scalars(select(User).where(User.email == "quark-row@example.com")).one()
        account = PanAccount(
            user_id=user.id,
            provider="quark",
            nickname="夸克",
            cookie_ciphertext=encrypt_cookie(COOKIE, KEY),
            status="valid",
        )
        session.add(account)
        session.commit()
        account_id = account.id
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/share/password"):
            return httpx.Response(200, json={"status": 200, "data": {"share_url": "https://pan.quark.cn/s/openrow", "passcode": ""}})
        if path.endswith("/task"):
            return httpx.Response(200, json={"status": 200, "data": {"status": 2, "share_id": "share-id"}})
        if path.endswith("/share"):
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"status": 200, "data": {"task_id": "task-1"}})
        raise AssertionError(path)

    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))
    shared = client.post(
        f"/api/accounts/{account_id}/files/share",
        json={"fs_id": None, "path": "/file-1", "name": "电影"},
    )
    assert shared.status_code == 200
    assert shared.json() == {"url": "https://pan.quark.cn/s/openrow", "password": ""}
    assert seen["body"]["url_type"] == 1
    assert "passcode" not in seen["body"]


def test_quark_public_share_omits_the_passcode():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/share/password"):
            return httpx.Response(200, json={"status": 200, "data": {"share_url": "https://pan.quark.cn/s/open1", "passcode": ""}})
        if path.endswith("/task"):
            return httpx.Response(200, json={"status": 200, "data": {"status": 2, "share_id": "share-id"}})
        if path.endswith("/share"):
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"status": 200, "data": {"task_id": "task-1"}})
        raise AssertionError(path)

    url, password = adapter_for("quark", client_for(handler)).create_share(
        COOKIE,
        None,
        "",
        "0",
        path="/fid-1",
        name="电影",
        sleeper=lambda _seconds: None,
    )
    assert url == "https://pan.quark.cn/s/open1"
    assert password == ""
    assert seen["body"] == {
        "fid_list": ["fid-1"],
        "title": "电影",
        "url_type": 1,
        "expired_type": 1,
    }


def test_quark_thirty_day_share_uses_expired_type_four():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/share/password"):
            return httpx.Response(200, json={"status": 200, "data": {"share_url": "https://pan.quark.cn/s/month1", "passcode": "abcd"}})
        if path.endswith("/task"):
            return httpx.Response(200, json={"status": 200, "data": {"status": 2, "share_id": "share-id"}})
        if path.endswith("/share"):
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"status": 200, "data": {"task_id": "task-1"}})
        raise AssertionError(path)

    adapter_for("quark", client_for(handler)).create_share(
        COOKIE,
        None,
        "ab12",
        "30",
        path="/fid-1",
        name="电影",
        sleeper=lambda _seconds: None,
    )
    assert seen["body"]["expired_type"] == 4


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


def test_daily_sync_skips_quark_account(client):
    response = client.post("/api/auth/register", json={"email": "quark-sync@example.com", "password": "password-123"})
    assert response.status_code == 201
    with client.app.state.session_factory() as session:
        user = session.scalars(select(User).where(User.email == "quark-sync@example.com")).one()
        user.plan = "paid"
        user.plan_expires_at = NOW + timedelta(days=30)
        account = PanAccount(
            user_id=user.id,
            provider="quark",
            nickname="夸克",
            cookie_ciphertext=encrypt_cookie(COOKIE, KEY),
            status="valid",
        )
        session.add(account)
        session.commit()
        account_id = account.id
        enqueue_daily_syncs(session, datetime(2026, 9, 22, 16, 5, tzinfo=timezone.utc))
        session.commit()
        jobs = session.scalars(select(Job).where(Job.account_id == account_id, Job.type == "sync")).all()
        assert jobs == []
    denied = client.post(f"/api/accounts/{account_id}/sync")
    assert denied.status_code == 422
    assert denied.json()["detail"] == "只有百度网盘需要同步"


def test_quark_sync_leaves_existing_links_untouched(client):
    response = client.post("/api/auth/register", json={"email": "quark-fail@example.com", "password": "password-123"})
    assert response.status_code == 201
    with client.app.state.session_factory() as session:
        user = session.scalars(select(User).where(User.email == "quark-fail@example.com")).one()
        account = PanAccount(
            user_id=user.id,
            provider="quark",
            nickname="夸克",
            cookie_ciphertext=encrypt_cookie(COOKIE, KEY),
            status="valid",
        )
        session.add(account)
        session.flush()
        share = ShareLink(
            user_id=user.id,
            account_id=account.id,
            baidu_share_id="old",
            name="旧分享",
            path="/旧分享",
            url="https://pan.quark.cn/s/old",
            status="active",
            created_at=NOW,
        )
        session.add(share)
        session.flush()
        session.add(
            ShareStatSnapshot(
                share_link_id=share.id,
                account_id=account.id,
                transfer_count=1,
                view_count=1,
                download_count=0,
                taken_at=NOW,
            )
        )
        job = Job(
            user_id=user.id,
            account_id=account.id,
            type="sync",
            status="pending",
            directory="/",
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(job)
        session.commit()
        share_id, job_id = share.id, job.id

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(request.url)

    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))
    with client.app.state.session_factory() as session:
        execute_sync(session, client.app.state.pan_http_client, session.get(Job, job_id), lambda _seconds: None, NOW)
        session.commit()
        stored = session.get(ShareLink, share_id)
        assert session.get(Job, job_id).status == "succeeded"
        assert stored.status == "active"
        assert stored.name == "旧分享"
        assert len(session.scalars(select(ShareStatSnapshot)).all()) == 1


def test_quark_copy_posts_filelist_to_parent():
    calls = {"sort": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/file/sort"):
            calls["sort"] += 1
            if calls["sort"] == 1:
                return httpx.Response(200, json={"status": 200, "data": {"list": []}})
            return httpx.Response(
                200,
                json={
                    "status": 200,
                    "data": {
                        "list": [
                            {
                                "fid": "fid-new",
                                "file_name": "源名",
                                "file_type": 0,
                                "created_at": 1600000000000,
                                "updated_at": 1700000000000,
                            }
                        ]
                    },
                },
            )
        if path.endswith("/file/copy"):
            body = json.loads(request.content.decode())
            assert body["filelist"] == ["fid-src"]
            assert body["to_pdir_fid"] == "fid-dest"
            return httpx.Response(200, json={"status": 200, "data": {"task_id": "t1"}})
        if path.endswith("/task"):
            return httpx.Response(200, json={"status": 200, "data": {"status": 2}})
        if path.endswith("/file/rename"):
            body = json.loads(request.content.decode())
            assert body == {"fid": "fid-new", "file_name": "新名字"}
            return httpx.Response(200, json={"status": 200, "data": {}})
        raise AssertionError(path)

    adapter_for("quark", client_for(handler)).copy(COOKIE, "/fid-src", "/fid-dest", "新名字")


def test_quark_copy_raises_when_name_exists():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/file/sort")
        return httpx.Response(
            200,
            json={"status": 200, "data": {"list": [{"fid": "x", "file_name": "同名", "file_type": 0}]}},
        )

    with pytest.raises(DuplicateName):
        adapter_for("quark", client_for(handler)).copy(COOKIE, "/fid-src", "/fid-dest", "同名")
