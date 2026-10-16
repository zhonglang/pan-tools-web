import httpx
import pytest

from app.pans import LoginRejected, adapter_for

COOKIE = "BDUSS=super-secret-cookie-value"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_baidu_verify_uses_netdisk_name():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.host == "pan.baidu.com"
        assert request.url.params["method"] == "uinfo"
        assert request.headers["cookie"] == COOKIE
        assert request.headers["user-agent"] == UA
        return httpx.Response(200, json={"errno": 0, "netdisk_name": "网盘昵称", "baidu_name": "百度名"})

    nickname = adapter_for("baidu", client_for(handler)).verify_login(COOKIE)
    assert nickname == "网盘昵称"


def test_baidu_verify_falls_back_to_baidu_name():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errno": 0, "netdisk_name": "  ", "baidu_name": "百度名"})

    nickname = adapter_for("baidu", client_for(handler)).verify_login(COOKIE)
    assert nickname == "百度名"


def test_baidu_verify_rejects_bad_cookie():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errno": -6})

    with pytest.raises(LoginRejected):
        adapter_for("baidu", client_for(handler)).verify_login(COOKIE)


def test_baidu_verify_rejects_non_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>login</html>")

    with pytest.raises(LoginRejected):
        adapter_for("baidu", client_for(handler)).verify_login(COOKIE)


QUARK_COOKIE = "b-user-id=1; __pus=secret"


def test_quark_verify_returns_nickname():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "drive-pc.quark.cn"
        assert request.url.path == "/1/clouddrive/member"
        assert request.headers["cookie"] == QUARK_COOKIE
        return httpx.Response(200, json={"status": 200, "data": {"nickname": "夸克昵称"}})

    nickname = adapter_for("quark", client_for(handler)).verify_login(QUARK_COOKIE)
    assert nickname == "夸克昵称"


def test_quark_verify_accepts_a_member_response_without_nickname():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 200, "data": {"member_type": "NORMAL"}})

    assert adapter_for("quark", client_for(handler)).verify_login(QUARK_COOKIE) == "夸克用户"


def test_quark_verify_rejects_bad_cookie():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 401, "message": "未登录"})

    with pytest.raises(LoginRejected):
        adapter_for("quark", client_for(handler)).verify_login(QUARK_COOKIE)


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="网盘类型无效"):
        adapter_for("dropbox", client_for(lambda request: httpx.Response(500)))
