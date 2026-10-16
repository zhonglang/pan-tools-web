import json
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.core.crypto import encrypt_cookie
from app.models import DailyUsage, Job, JobItem, PanAccount, User
from app.services.quota import shanghai_today
from app.services.transfers import execute_job, reclaim_stale

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
    assert reasons == [None, "提取码错误"]
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
        if "disk/home" in url:
            return httpx.Response(200, text="home")
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


def test_create_folder_rejects_a_bad_name(client):
    register(client)
    account_id = bind(client)
    created = client.post(f"/api/accounts/{account_id}/folders", json={"directory": "/", "name": "../秘密"})
    assert created.status_code == 422
    assert created.json()["detail"] == "文件夹名称无效"


def test_create_folder_returns_the_new_path(client):
    register(client)
    account_id = bind(client)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        if "api/create" in url:
            assert COOKIE not in url
            return httpx.Response(200, json={"errno": 0})
        raise AssertionError(url)

    install(client, handler)
    created = client.post(f"/api/accounts/{account_id}/folders", json={"directory": "/毕业照", "name": "新相册"})
    assert created.status_code == 201
    assert created.json() == {
        "name": "新相册",
        "path": "/毕业照/新相册",
        "is_dir": True,
        "size": None,
        "created_at": None,
        "modified_at": None,
        "fs_id": None,
    }
    assert COOKIE not in created.text


def test_chinese_share_card_becomes_one_item(client):
    register(client)
    account_id = bind(client)
    created = client.post("/api/transfers", json={
        "account_id": account_id,
        "directory": "/",
        "links": (
            "【超级会员V4】通过百度网盘分享的文件：【韩剧】挑情丑闻\n"
            "链接:https://pan.baidu.com/s/1kBdgMqBHCFBpexkIfIpIZw?pwd=6666\u00a0\n"
            "复制这段内容打开「百度网盘APP 即可获取」"
        ),
    })
    assert created.status_code == 201
    items = created.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "pending"
    assert items[0]["input_text"] == "https://pan.baidu.com/s/1kBdgMqBHCFBpexkIfIpIZw?pwd=6666"
    with client.app.state.session_factory() as session:
        usage = session.scalars(select(DailyUsage)).one()
        assert usage.transfer_count == 1


def test_rename_and_folder_download(client):
    from urllib.parse import parse_qs

    register(client)
    account_id = bind(client)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        assert COOKIE not in url
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        if "filemanager" in url:
            form = parse_qs(request.content.decode())
            assert json.loads(form["filelist"][0]) == [{"path": "/说明.txt", "newname": "新说明.txt"}]
            return httpx.Response(200, json={"errno": 0})
        if "locatedownload" in url:
            return httpx.Response(403, json={"error_code": 31074})
        raise AssertionError(url)

    install(client, handler)
    renamed = client.post(f"/api/accounts/{account_id}/files/rename", json={"path": "/说明.txt", "name": "新说明.txt"})
    assert renamed.status_code == 200
    assert renamed.json() == {"ok": True}
    assert COOKIE not in renamed.text
    blocked = client.get(f"/api/accounts/{account_id}/files/download", params={"path": "/毕业照"})
    assert blocked.status_code == 422
    assert blocked.json()["detail"] == "文件夹请进入后下载其中的文件"
    root = client.post(f"/api/accounts/{account_id}/files/delete", json={"path": "/"})
    assert root.status_code == 422
    assert root.json()["detail"] == "不能操作根目录"


def test_folder_download_returns_a_zip(client):
    import io
    import zipfile

    register(client)
    account_id = bind(client)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        if "xpan/file" in url:
            directory = request.url.params["dir"]
            if directory == "/毕业照":
                return httpx.Response(200, json={"errno": 0, "list": [
                    {"server_filename": "说明.txt", "path": "/毕业照/说明.txt", "isdir": 0, "size": 5},
                    {"server_filename": "子目录", "path": "/毕业照/子目录", "isdir": 1},
                ]})
            if directory == "/毕业照/子目录":
                return httpx.Response(200, json={"errno": 0, "list": [
                    {"server_filename": "b.txt", "path": "/毕业照/子目录/b.txt", "isdir": 0, "size": 3},
                ]})
        if "locatedownload" in url:
            name = "hello" if request.url.params["path"].endswith("说明.txt") else "yes"
            return httpx.Response(200, json={"urls": [{"url": f"https://d.pcs.baidu.com/file?name={name}"}]})
        if request.url.host == "d.pcs.baidu.com":
            body = b"hello" if request.url.params["name"] == "hello" else b"yes"
            return httpx.Response(200, content=body)
        raise AssertionError(url)

    install(client, handler)
    response = client.get(f"/api/accounts/{account_id}/files/download", params={"path": "/毕业照", "folder": 1})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert int(response.headers["content-length"]) == len(response.content)
    assert "attachment" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.read("毕业照/说明.txt") == b"hello"
        assert archive.read("毕业照/子目录/b.txt") == b"yes"


def test_folder_save_writes_the_directory_tree(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PAN_DOWNLOAD_DIR", str(tmp_path / "downloads"))
    register(client)
    account_id = bind(client)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        if "xpan/file" in url:
            directory = request.url.params["dir"]
            if directory == "/毕业照":
                return httpx.Response(200, json={"errno": 0, "list": [
                    {"server_filename": "说明.txt", "path": "/毕业照/说明.txt", "isdir": 0, "size": 5},
                    {"server_filename": "子目录", "path": "/毕业照/子目录", "isdir": 1},
                    {"server_filename": "空目录", "path": "/毕业照/空目录", "isdir": 1},
                ]})
            if directory == "/毕业照/子目录":
                return httpx.Response(200, json={"errno": 0, "list": [
                    {"server_filename": "b.txt", "path": "/毕业照/子目录/b.txt", "isdir": 0, "size": 3},
                ]})
            if directory == "/毕业照/空目录":
                return httpx.Response(200, json={"errno": 0, "list": []})
        if "locatedownload" in url:
            name = "hello" if request.url.params["path"].endswith("说明.txt") else "yes"
            return httpx.Response(200, json={"urls": [{"url": f"https://d.pcs.baidu.com/file?name={name}"}]})
        if request.url.host == "d.pcs.baidu.com":
            body = b"hello" if request.url.params["name"] == "hello" else b"yes"
            return httpx.Response(200, content=body)
        raise AssertionError(url)

    install(client, handler)
    created = client.post(f"/api/accounts/{account_id}/files/save", json={"path": "/毕业照"})
    assert created.status_code == 201
    task = wait_download(client, created.json()["id"])
    assert task["status"] == "done"
    assert task["bytes_total"] == 8
    assert task["bytes_done"] == 8
    assert task["files_done"] == 2
    saved = (tmp_path / "downloads" / "毕业照").resolve()
    assert (saved / "说明.txt").read_bytes() == b"hello"
    assert (saved / "子目录" / "b.txt").read_bytes() == b"yes"
    assert (saved / "空目录").is_dir()
    assert task["directory"] == str(saved)
    assert task["created_at"]
    listed = client.get("/api/downloads")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == task["id"]
    assert listed.json()[0]["status"] == "done"


def test_running_download_can_be_cancelled(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PAN_DOWNLOAD_DIR", str(tmp_path / "downloads"))
    register(client)
    account_id = bind(client)
    started = threading.Event()
    release = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        if "xpan/file" in url:
            return httpx.Response(200, json={"errno": 0, "list": [
                {"server_filename": "大文件.bin", "path": "/相册/大文件.bin", "isdir": 0, "size": 4},
            ]})
        if "locatedownload" in url:
            return httpx.Response(200, json={"urls": [{"url": "https://d.pcs.baidu.com/file?name=big"}]})
        if request.url.host == "d.pcs.baidu.com":
            started.set()
            assert release.wait(5)
            return httpx.Response(200, content=b"data")
        raise AssertionError(url)

    install(client, handler)
    created = client.post(f"/api/accounts/{account_id}/files/save", json={"path": "/相册"})
    assert created.status_code == 201
    task_id = created.json()["id"]
    assert started.wait(3)
    cancelled = client.post(f"/api/downloads/{task_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    release.set()
    task = wait_download(client, task_id)
    assert task["status"] == "cancelled"
    listed = client.get("/api/downloads").json()
    assert listed[0]["id"] == task_id
    assert listed[0]["status"] == "cancelled"


def wait_download(client, task_id: int):
    last = None
    deadline = time.time() + 5
    while time.time() < deadline:
        rows = client.get("/api/downloads").json()
        last = next(row for row in rows if row["id"] == task_id)
        if last["status"] != "running":
            return last
        time.sleep(0.05)
    raise AssertionError(last)


def test_download_name_keeps_the_clicked_folder():
    from urllib.parse import unquote

    from app.api.routes.transfers import safe_attachment_name

    assert unquote(safe_attachment_name("毕业照/子目录/说明.txt", "说明.txt")) == "毕业照／子目录／说明.txt"
    assert unquote(safe_attachment_name("../秘密", "说明.txt")) == "说明.txt"


def test_transfer_stores_the_folder_name_separately_from_the_id(client):
    register(client)
    account_id = bind(client)
    install(client, list_ok)
    created = client.post("/api/transfers", json={
        "account_id": account_id,
        "directory": "/308b540179274ef7b2dd6713da9f5180",
        "directory_label": "根目录 / 我的资料",
        "links": "https://pan.baidu.com/s/1AbCdEf ab12",
    })
    assert created.status_code == 201
    assert created.json()["directory"] == "/308b540179274ef7b2dd6713da9f5180"
    assert created.json()["directory_label"] == "根目录 / 我的资料"
    listed = client.get("/api/jobs")
    assert listed.json()[0]["directory_label"] == "根目录 / 我的资料"
    assert listed.json()[0]["directory"] == "/308b540179274ef7b2dd6713da9f5180"


def test_running_transfer_is_visible_before_the_batch_finishes(client):
    register(client)
    account_id = bind(client)
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "xpan/file" in url:
            return httpx.Response(200, json={"errno": 0, "list": []})
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        if "share/verify" in url:
            return httpx.Response(200, json={"errno": 0, "randsk": "rand-sk"})
        if "share/list" in url:
            return httpx.Response(200, json={"errno": 0, "share_id": 9, "uk": 8, "list": [{"fs_id": 11}]})
        if "share/transfer" in url:
            with client.app.state.session_factory() as other:
                job = other.scalars(select(Job)).one()
                item = other.scalars(select(JobItem)).one()
                seen["job"] = job.status
                seen["item"] = item.status
            return httpx.Response(200, json={"errno": 0})
        raise AssertionError(url)

    install(client, handler)
    created = client.post("/api/transfers", json={
        "account_id": account_id,
        "directory": "/",
        "links": "https://pan.baidu.com/s/1AbCdEf ab12",
    })
    assert created.status_code == 201
    with client.app.state.session_factory() as session:
        execute_job(session, client.app.state.pan_http_client, session.get(Job, created.json()["id"]), sleeper=lambda _seconds: None, now=NOW)
        session.commit()
    assert seen == {"job": "running", "item": "pending"}
    shown = client.get(f"/api/jobs/{created.json()['id']}")
    assert shown.json()["status"] == "succeeded"


def test_job_list_shows_created_transfers(client):
    register(client)
    account_id = bind(client)
    created = client.post("/api/transfers", json={
        "account_id": account_id,
        "directory": "/",
        "links": "https://pan.baidu.com/s/1AbCdEf ab12",
    })
    assert created.status_code == 201
    listed = client.get("/api/jobs")
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["id"] == created.json()["id"]
    assert rows[0]["status"] == "pending"
    assert rows[0]["directory"] == "/"
    assert rows[0]["total"] == 1
    assert rows[0]["type"] == "transfer"
