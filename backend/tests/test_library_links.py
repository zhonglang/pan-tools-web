import httpx

from app.models.library import LibraryItem
from app.services.library_links import check_library_links, classify_baidu, classify_quark, classify_xunlei
from tests.test_library import register


def test_baidu_dead_code_is_invalid_and_a_wrong_password_is_not():
    assert classify_baidu({"errno": 105}) == "invalid"
    assert classify_baidu({"errno": -21}) == "invalid"
    assert classify_baidu({"errno": 0}) == "ok"
    assert classify_baidu({"errno": -9}) == "ok"
    assert classify_baidu({"errno": 31034}) == "unknown"


def test_quark_missing_share_is_invalid_and_an_extract_code_error_is_not():
    assert classify_quark({"status": 404, "message": "分享不存在"}) == "invalid"
    assert classify_quark({"status": 400, "message": "需要提取码"}) == "ok"
    assert classify_quark({"status": 200, "data": {"expired_at": 1}}, now=10) == "invalid"
    assert classify_quark({"status": 200, "data": {"expired_at": 0}}, now=10) == "ok"


def test_xunlei_not_found_is_invalid_and_a_bad_code_is_not():
    assert classify_xunlei({"share_status": "NOT_FOUND"}) == "invalid"
    assert classify_xunlei({"share_status": "OK"}) == "ok"
    assert classify_xunlei({"share_status": "PASS_CODE_ERROR"}) == "ok"
    assert classify_xunlei({"error": "captcha_invalid", "error_code": 9}) == "unknown"


def test_check_collects_only_dead_links(client):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/share/verify"):
            errno = 105 if request.url.params["surl"] == "deadbd" else 0
            return httpx.Response(200, json={"errno": errno})
        if path.endswith("/share/sharepage/token"):
            return httpx.Response(404, json={"status": 404, "message": "分享不存在"})
        if path.endswith("/shield/captcha/init"):
            return httpx.Response(200, json={"captcha_token": "cap"})
        if path.endswith("/share"):
            status = "NOT_FOUND" if request.url.params["share_id"] == "deadxl" else "OK"
            return httpx.Response(200, json={"share_status": status, "files": []})
        raise AssertionError(path)

    items = [
        LibraryItem(id=1, user_id=1, prefix="001", name="失效的", baidu_url="https://pan.baidu.com/s/1deadbd", quark_url="https://pan.quark.cn/s/deadqk", xunlei_url="https://pan.xunlei.com/s/deadxl?pwd=ab12"),
        LibraryItem(id=2, user_id=1, prefix="002", name="还在的", baidu_url="https://pan.baidu.com/s/1livebd 提取码: cd34", quark_url="", xunlei_url=""),
    ]
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        result = check_library_links(items, http)
    assert result.checked == 4
    assert result.unknown == 0
    assert [(hit.prefix, hit.provider) for hit in result.invalid] == [
        ("001", "baidu"),
        ("001", "quark"),
        ("001", "xunlei"),
    ]


def test_check_route_lists_dead_links_for_the_current_user(client, monkeypatch):
    register(client)
    created = client.post("/api/library/import", json={"rows": [
        {"name": "009 朝朝", "url": "https://pan.baidu.com/s/1alive", "password": ""},
    ]})
    item_id = created.json()["items"][0]["id"]

    def fake(items, _client):
        from app.services.library_links import DeadLink, LinkCheck

        assert len(items) == 1
        return LinkCheck(
            checked=1,
            unknown=1,
            invalid=[DeadLink(id=item_id, prefix="009", name="朝朝", provider="baidu", reason="链接已失效")],
        )

    monkeypatch.setattr("app.api.routes.library.check_library_links", fake)
    checked = client.post("/api/library/check")
    assert checked.status_code == 200
    assert checked.json() == {
        "checked": 1,
        "unknown": 1,
        "invalid": [{"id": item_id, "prefix": "009", "name": "朝朝", "provider": "baidu", "reason": "链接已失效"}],
    }

    register(client, "library-other@example.com")

    def empty(items, _client):
        from app.services.library_links import LinkCheck

        assert items == []
        return LinkCheck(checked=0, invalid=[], unknown=0)

    monkeypatch.setattr("app.api.routes.library.check_library_links", empty)
    others = client.post("/api/library/check")
    assert others.status_code == 200
    assert others.json()["invalid"] == []


def test_check_route_requires_login(client):
    assert client.post("/api/library/check").status_code == 401
