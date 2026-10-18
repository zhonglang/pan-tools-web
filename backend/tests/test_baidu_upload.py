import hashlib
import io
from urllib.parse import parse_qs

import httpx
import pytest

from app.pans.baidu import BaiduAdapter
from app.pans.errors import UploadCancelled

COOKIE = "BDUSS=super-secret-cookie-value"


def test_baidu_upload_file_happy_path():
    content = b"hello-baidu"
    digest = hashlib.md5(content).hexdigest()
    calls = {"precreate": 0, "slice": 0, "create": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        if "api/precreate" in url:
            calls["precreate"] += 1
            form = parse_qs(request.content.decode())
            assert form["path"] == ["/测试/a.txt"]
            assert form["size"] == [str(len(content))]
            return httpx.Response(
                200,
                json={"errno": 0, "uploadid": "up-1", "return_type": 1, "block_list": [0]},
            )
        if "superfile2" in url:
            calls["slice"] += 1
            assert request.url.params["uploadid"] == "up-1"
            assert request.url.params["partseq"] == "0"
            return httpx.Response(200, json={"md5": digest, "request_id": 1})
        if "api/create" in url:
            calls["create"] += 1
            form = parse_qs(request.content.decode())
            assert form["path"] == ["/测试/a.txt"]
            assert form["uploadid"] == ["up-1"]
            return httpx.Response(200, json={"errno": 0})
        raise AssertionError(url)

    progress = []
    BaiduAdapter(httpx.Client(transport=httpx.MockTransport(handler))).upload_file(
        COOKIE,
        "/测试",
        "a.txt",
        io.BytesIO(content),
        len(content),
        on_progress=progress.append,
    )
    assert calls == {"precreate": 1, "slice": 1, "create": 1}
    assert progress == [len(content)]


def test_baidu_upload_rapid_skips_slices():
    content = b"rapid"

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        if "api/precreate" in url:
            return httpx.Response(200, json={"errno": 0, "return_type": 2})
        raise AssertionError(url)

    progress = []
    BaiduAdapter(httpx.Client(transport=httpx.MockTransport(handler))).upload_file(
        COOKIE,
        "/",
        "r.txt",
        io.BytesIO(content),
        len(content),
        on_progress=progress.append,
    )
    assert progress == [len(content)]


def test_baidu_upload_cancel_before_slice():
    content = b"x" * 10
    stop = {"value": False}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        if "api/precreate" in url:
            stop["value"] = True
            return httpx.Response(
                200,
                json={"errno": 0, "uploadid": "up-1", "return_type": 1, "block_list": [0]},
            )
        raise AssertionError(url)

    with pytest.raises(UploadCancelled):
        BaiduAdapter(httpx.Client(transport=httpx.MockTransport(handler))).upload_file(
            COOKIE,
            "/",
            "c.txt",
            io.BytesIO(content),
            len(content),
            should_stop=lambda: stop["value"],
        )
