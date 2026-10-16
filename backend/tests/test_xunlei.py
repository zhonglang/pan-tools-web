import json
import time

import httpx
import pytest

from app.pans import adapter_for
from app.pans.errors import DuplicateName, WrongPassword

COOKIE = json.dumps(
    {
        "access_token": "access-1",
        "captcha_token": "cap-1",
        "device_id": "a" * 32,
        "refresh_token": "refresh-1",
        "user_id": "user-1",
    },
    separators=(",", ":"),
    sort_keys=True,
)


def _cookie(**overrides):
    payload = {
        "access_token": "access-1",
        "captcha_token": "cap-1",
        "client_id": "Xp6vsxz_7IYVw2BB",
        "device_id": "a" * 32,
        "refresh_token": "refresh-1",
        "user_id": "user-1",
    }
    payload.update(overrides)
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_xunlei_verify_returns_the_account_name():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/user/me"
        assert request.headers["authorization"] == "Bearer access-1"
        assert request.headers["x-captcha-token"] == "cap-1"
        return httpx.Response(200, json={"name": "迅雷昵称"})

    assert adapter_for("xunlei", client_for(handler)).verify_login(COOKIE) == "迅雷昵称"


def test_xunlei_list_dir_uses_file_ids():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["parent_id"] == ""
        return httpx.Response(
            200,
            json={
                "files": [
                    {
                        "id": "folder-1",
                        "name": "电影",
                        "kind": "drive#folder",
                        "size": "0",
                        "created_time": "2026-01-01T00:00:00Z",
                        "modified_time": "2026-01-02T00:00:00Z",
                    }
                ],
                "next_page_token": "",
            },
        )

    rows = adapter_for("xunlei", client_for(handler)).list_dir(COOKIE, "/")
    assert rows[0].name == "电影"
    assert rows[0].path == "/folder-1"
    assert rows[0].is_dir is True
    assert rows[0].size == 0
    assert rows[0].created_at == 1767225600
    assert rows[0].modified_at == 1767312000


def test_xunlei_thirty_day_share_sends_expiration_days():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"share_id": "V30", "share_url": "https://pan.xunlei.com/s/V30", "pass_code": "g298"},
        )

    url, password = adapter_for("xunlei", client_for(handler)).create_share(
        COOKIE,
        None,
        "ab12",
        "30",
        path="/folder-1",
        name="电影",
        sleeper=lambda _seconds: None,
    )
    assert url == "https://pan.xunlei.com/s/V30?pwd=g298#"
    assert password == "g298"
    assert seen["body"]["expiration_days"] == "30"
    assert "pass_code" not in seen["body"]
    assert seen["body"]["params"] == {"withPassCodeInLink": "true"}


def test_xunlei_quick_share_puts_the_generated_code_in_the_link():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "share_id": "Vopen",
                "share_url": "https://pan.xunlei.com/s/Vopen?pwd=old#",
                "pass_code": "zzzz",
            },
        )

    url, password = adapter_for("xunlei", client_for(handler)).create_share(
        COOKIE,
        None,
        "",
        "0",
        path="/folder-1",
        name="电影",
    )
    assert url == "https://pan.xunlei.com/s/Vopen?pwd=zzzz#"
    assert password == "zzzz"
    assert "pass_code" not in seen["body"]
    assert seen["body"]["params"] == {"withPassCodeInLink": "true"}
    assert seen["body"]["expiration_days"] == "-1"


def test_xunlei_transfer_restores_the_share():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/share/restore"):
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"restore_status": "RESTORE_COMPLETE"})
        return httpx.Response(
            200,
            json={"pass_code_token": "token-1", "files": [{"id": "file-1", "name": "电影", "kind": "drive#file"}]},
        )

    adapter_for("xunlei", client_for(handler)).transfer_share(COOKIE, "https://pan.xunlei.com/s/V1", "ab12", "/")
    assert seen["body"]["share_id"] == "V1"
    assert seen["body"]["file_ids"] == ["file-1"]
    assert seen["body"]["parent_id"] == ""
    assert seen["body"]["pass_code_token"] == "token-1"


def test_xunlei_wrong_passcode_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "pass_code_invalid", "error_description": "提取码错误"})

    try:
        adapter_for("xunlei", client_for(handler)).transfer_share(COOKIE, "V1", "0000", "/")
    except WrongPassword:
        return
    raise AssertionError("expected WrongPassword")


def test_xunlei_share_list_keeps_missing_counts_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "share_id": "V1",
                        "share_url": "https://pan.xunlei.com/s/V1",
                        "title": "电影",
                        "restore_count": 2,
                    }
                ],
                "next_page_token": "",
            },
        )

    records = adapter_for("xunlei", client_for(handler)).list_share_records(COOKIE)
    assert records[0]["transfers"] == 2
    assert records[0]["views"] is None
    assert records[0]["downloads"] is None


def test_xunlei_copy_posts_to_parent():
    calls = {"list": 0, "task": 0}
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/files:batchCopy"):
            body = json.loads(request.content.decode())
            assert body["ids"] == ["fid-src"]
            assert body["to"]["parent_id"] == "fid-dest"
            return httpx.Response(200, json={"task_id": "task-copy-1", "space": ""})
        if request.url.path.endswith("/tasks/task-copy-1"):
            calls["task"] += 1
            phase = "PHASE_TYPE_RUNNING" if calls["task"] == 1 else "PHASE_TYPE_COMPLETE"
            return httpx.Response(
                200,
                json={"id": "task-copy-1", "phase": phase, "message": "已添加", "type": "copy"},
            )
        if request.url.path.endswith("/files") and request.method == "GET":
            calls["list"] += 1
            if calls["list"] == 1:
                return httpx.Response(200, json={"files": [], "next_page_token": ""})
            return httpx.Response(
                200,
                json={
                    "files": [
                        {
                            "id": "fid-new",
                            "name": "源名",
                            "kind": "drive#folder",
                            "size": "0",
                            "phase": "PHASE_TYPE_COMPLETE",
                        }
                    ],
                    "next_page_token": "",
                },
            )
        if request.method == "PATCH" and request.url.path.endswith("/files/fid-new"):
            body = json.loads(request.content.decode())
            assert body == {"name": "新名字"}
            return httpx.Response(200, json={})
        raise AssertionError(f"{request.method} {request.url.path}")

    adapter_for("xunlei", client_for(handler)).copy(
        COOKIE, "/fid-src", "/fid-dest", "新名字", sleeper=sleeps.append
    )
    assert calls["task"] >= 2
    assert sleeps


def test_xunlei_copy_raises_when_name_exists():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "files": [
                    {
                        "id": "x",
                        "name": "同名",
                        "kind": "drive#folder",
                        "size": "0",
                        "phase": "PHASE_TYPE_COMPLETE",
                    }
                ],
                "next_page_token": "",
            },
        )

    with pytest.raises(DuplicateName):
        adapter_for("xunlei", client_for(handler)).copy(COOKIE, "/fid-src", "/fid-dest", "同名")


def test_xunlei_prepare_refreshes_when_access_expired():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/auth/token"):
            calls.append("refresh")
            body = json.loads(request.content.decode())
            assert body["refresh_token"] == "refresh-1"
            return httpx.Response(
                200,
                json={"access_token": "access-2", "refresh_token": "refresh-2", "expires_in": 7200},
            )
        if path.endswith("/captcha/init"):
            calls.append("captcha")
            return httpx.Response(200, json={"captcha_token": "cap-2"})
        raise AssertionError(path)

    warmed = adapter_for("xunlei", client_for(handler)).prepare(_cookie(expires_at=1))
    data = json.loads(warmed)
    assert data["access_token"] == "access-2"
    assert data["refresh_token"] == "refresh-2"
    assert data["captcha_token"] == "cap-2"
    assert data["expires_at"] >= int(time.time()) + 7100
    assert calls == ["refresh", "captcha"]


def test_xunlei_uses_warmed_token_after_refresh():
    calls = {"files": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/files") and request.method == "GET":
            calls["files"] += 1
            auth = request.headers.get("authorization")
            if calls["files"] == 1:
                assert auth == "Bearer access-1"
                return httpx.Response(401, json={"error_code": 16, "error": "unauthenticated"})
            assert auth == "Bearer access-2"
            return httpx.Response(200, json={"files": [], "next_page_token": ""})
        if path.endswith("/auth/token"):
            return httpx.Response(
                200,
                json={"access_token": "access-2", "refresh_token": "refresh-2", "expires_in": 7200},
            )
        if path.endswith("/captcha/init"):
            return httpx.Response(200, json={"captcha_token": "cap-2"})
        raise AssertionError(f"{request.method} {path}")

    adapter = adapter_for("xunlei", client_for(handler))
    assert adapter.list_dir(_cookie(expires_at=int(time.time()) + 3600), "/") == []
    # Second call must use rotated tokens from warmed, not the original cookie string.
    assert adapter.list_dir(_cookie(expires_at=int(time.time()) + 3600), "/") == []
    assert calls["files"] == 3  # 401 + retry + second list_dir
    assert json.loads(adapter.warmed)["refresh_token"] == "refresh-2"
