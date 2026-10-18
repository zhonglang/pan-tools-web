import io

import httpx

from app.pans.quark import QuarkAdapter

COOKIE = "ck=1"


def test_quark_upload_rapid_finish():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/file/upload/pre"):
            return httpx.Response(
                200,
                json={
                    "status": 200,
                    "data": {"task_id": "t1", "bucket": "b", "obj_key": "k", "upload_id": "u", "upload_url": "https://oss.example"},
                    "metadata": {"part_size": 1024},
                },
            )
        if path.endswith("/file/update/hash"):
            return httpx.Response(200, json={"status": 200, "data": {"finish": True}})
        raise AssertionError(path)

    progress = []
    QuarkAdapter(httpx.Client(transport=httpx.MockTransport(handler))).upload_file(
        COOKIE,
        "/0",
        "a.txt",
        io.BytesIO(b"hello"),
        5,
        on_progress=progress.append,
    )
    assert progress == [5]


def test_quark_upload_multipart():
    seen = {"auth": 0, "put": 0, "commit": 0, "finish": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/file/upload/pre"):
            return httpx.Response(
                200,
                json={
                    "status": 200,
                    "data": {
                        "task_id": "t1",
                        "bucket": "mybucket",
                        "obj_key": "obj",
                        "upload_id": "up",
                        "upload_url": "https://oss.example.com",
                        "auth_info": {"x": 1},
                        "callback": {"cb": 1},
                    },
                    "metadata": {"part_size": 3},
                },
            )
        if path.endswith("/file/update/hash"):
            return httpx.Response(200, json={"status": 200, "data": {"finish": False}})
        if path.endswith("/file/upload/auth"):
            seen["auth"] += 1
            return httpx.Response(200, json={"status": 200, "data": {"auth_key": "OSS key"}})
        if path.endswith("/file/upload/finish"):
            seen["finish"] += 1
            return httpx.Response(200, json={"status": 200, "data": {}})
        if request.method == "PUT" and "mybucket.oss.example.com" in str(request.url):
            seen["put"] += 1
            return httpx.Response(200, headers={"ETag": '"etag1"'})
        if request.method == "POST" and "mybucket.oss.example.com" in str(request.url):
            seen["commit"] += 1
            return httpx.Response(200, content=b"ok")
        raise AssertionError(f"{request.method} {request.url}")

    progress = []
    QuarkAdapter(httpx.Client(transport=httpx.MockTransport(handler))).upload_file(
        COOKIE,
        "/",
        "a.txt",
        io.BytesIO(b"abcdef"),
        6,
        on_progress=progress.append,
    )
    assert seen["put"] == 2
    assert seen["commit"] == 1
    assert seen["finish"] == 1
    assert progress == [3, 3]
