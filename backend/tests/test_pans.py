import httpx
import pytest

from app.pans import LoginRejected, ProviderClosed, adapter_for

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


def test_closed_providers_do_not_call_http():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("closed provider must not send HTTP")

    for provider in ("quark", "xunlei"):
        with pytest.raises(ProviderClosed, match="暂未开放"):
            adapter_for(provider, client_for(handler)).verify_login(COOKIE)


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="网盘类型无效"):
        adapter_for("dropbox", client_for(lambda request: httpx.Response(500)))
