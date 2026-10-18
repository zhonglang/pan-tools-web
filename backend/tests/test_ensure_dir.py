from urllib.parse import parse_qs

import httpx

from app.pans.baidu import BaiduAdapter
from app.pans.quark import QuarkAdapter

COOKIE = "BDUSS=super-secret-cookie-value"


def test_baidu_ensure_dir_creates_missing_parents():
    created: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        if "api/create" in url:
            form = parse_qs(request.content.decode())
            created.append(form["path"][0])
            return httpx.Response(200, json={"errno": 0})
        raise AssertionError(url)

    BaiduAdapter(httpx.Client(transport=httpx.MockTransport(handler))).ensure_dir(COOKIE, "/a/b")
    assert created == ["/a", "/a/b"]


def test_baidu_ensure_subdir_joins_dest():
    created: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        if "api/create" in url:
            form = parse_qs(request.content.decode())
            path = form["path"][0]
            if path in created:
                return httpx.Response(200, json={"errno": -8})
            created.append(path)
            return httpx.Response(200, json={"errno": 0})
        raise AssertionError(url)

    path = BaiduAdapter(httpx.Client(transport=httpx.MockTransport(handler))).ensure_subdir(
        COOKIE, "/根", "子/孙"
    )
    assert path == "/根/子/孙"
    assert "/根/子" in created
    assert "/根/子/孙" in created


def test_quark_ensure_subdir_reuses_existing_folder():
    calls = {"list": 0, "create": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "GET" and "/file/sort" in url:
            calls["list"] += 1
            return httpx.Response(
                200,
                json={
                    "status": 200,
                    "data": {
                        "list": [
                            {"fid": "child-1", "file_name": "相册", "file_type": 0, "size": 0},
                        ]
                    },
                },
            )
        if request.method == "POST" and url.rstrip("/").endswith("/file"):
            calls["create"] += 1
            return httpx.Response(200, json={"status": 200, "data": {"fid": "new-1"}})
        raise AssertionError(f"{request.method} {url}")

    path = QuarkAdapter(httpx.Client(transport=httpx.MockTransport(handler))).ensure_subdir(
        "ck=1", "/", "相册"
    )
    assert path == "/child-1"
    assert calls["create"] == 0
    assert calls["list"] >= 1
