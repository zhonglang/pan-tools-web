import io
import json

import httpx

from app.pans.xunlei import XunleiAdapter, _gcid_hex

COOKIE = json.dumps(
    {
        "access_token": "access",
        "refresh_token": "refresh",
        "device_id": "d" * 32,
        "user_id": "u1",
        "captcha_token": "cap",
        "expires_at": 9999999999,
        "client_id": "Xp6vsxz_7IYVw2BB",
    }
)


def test_gcid_stable():
    assert len(_gcid_hex(b"hello")) == 40


def test_xunlei_upload_puts_to_s3():
    content = b"hello-xunlei"
    put_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and url.endswith("/drive/v1/files"):
            body = json.loads(request.content.decode())
            assert body["hash"] == _gcid_hex(content)
            assert body["upload_type"] == "UPLOAD_TYPE_RESUMABLE"
            return httpx.Response(
                200,
                json={
                    "upload_type": "UPLOAD_TYPE_RESUMABLE",
                    "resumable": {
                        "params": {
                            "bucket": "bucket1",
                            "key": "obj/key",
                            "endpoint": "https://oss.example.com",
                            "access_key_id": "AKI",
                            "access_key_secret": "SECRET",
                            "security_token": "TOKEN",
                        }
                    },
                },
            )
        if request.method == "PUT":
            put_urls.append(url)
            assert request.headers.get("authorization", "").startswith("AWS4-HMAC-SHA256")
            assert request.content == content
            return httpx.Response(200)
        raise AssertionError(f"{request.method} {url}")

    progress = []
    XunleiAdapter(httpx.Client(transport=httpx.MockTransport(handler))).upload_file(
        COOKIE,
        "/",
        "a.txt",
        io.BytesIO(content),
        len(content),
        on_progress=progress.append,
    )
    assert put_urls
    assert "bucket1" in put_urls[0]
    assert progress == [len(content)]
