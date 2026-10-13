import json

import httpx
import pytest

from app.pans.baidu import BaiduAdapter
from app.pans.errors import DuplicateName, InvalidLink, LoginRejected, NotAFile, PathNotFound, RateLimited, TransferFailed, WrongPassword

COOKIE = "BDUSS=super-secret-cookie-value"


def scripted(replies: list[tuple[str, dict]]):
    calls = {"n": 0, "urls": []}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["urls"].append(str(request.url))
        assert COOKIE not in str(request.url)
        kind, payload = replies[calls["n"]]
        calls["n"] += 1
        assert kind in str(request.url)
        if kind == "share/verify":
            assert request.url.params["surl"] == "AbCdEf"
            assert COOKIE in request.headers["cookie"]
            assert request.headers["referer"] == "https://pan.baidu.com/share/init?surl=AbCdEf"
        if kind == "share/list":
            assert "BDCLND=rand-sk" in request.headers["cookie"]
        if kind == "share/transfer":
            assert request.url.params["ondup"] == "fail"
            body = request.content.decode()
            assert "fsidlist=" in body
            encoded = body.split("fsidlist=")[1].split("&")[0]
            from urllib.parse import unquote

            assert json.loads(unquote(encoded)) == [11, 12]
        return httpx.Response(200, json=payload)

    return calls, httpx.Client(transport=httpx.MockTransport(handler))


def test_list_dir_returns_current_level():
    calls, client = scripted([
        ("xpan/file", {"errno": 0, "list": [
            {"server_filename": "片子", "path": "/片子", "isdir": 1},
            {"server_filename": "说明.txt", "path": "/说明.txt", "isdir": 0, "size": 2048, "server_ctime": 1600000000, "server_mtime": 1700000000, "fs_id": 42},
        ]}),
    ])
    entries = BaiduAdapter(client).list_dir(COOKIE, "/")
    assert [(item.name, item.path, item.is_dir) for item in entries] == [
        ("片子", "/片子", True),
        ("说明.txt", "/说明.txt", False),
    ]
    assert entries[1].size == 2048
    assert entries[1].created_at == 1600000000
    assert entries[1].modified_at == 1700000000
    assert entries[0].fs_id is None
    assert entries[1].fs_id == 42
    assert calls["n"] == 1


def test_missing_directory_and_bad_login():
    _, missing = scripted([("xpan/file", {"errno": -9})])
    with pytest.raises(PathNotFound):
        BaiduAdapter(missing).list_dir(COOKIE, "/没有")
    _, signed_out = scripted([("xpan/file", {"errno": -6})])
    with pytest.raises(LoginRejected):
        BaiduAdapter(signed_out).list_dir(COOKIE, "/没有")


def test_create_dir_posts_folder():
    from urllib.parse import parse_qs

    def handler(request: httpx.Request) -> httpx.Response:
        assert COOKIE not in str(request.url)
        if "gettemplatevariable" in str(request.url):
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        assert request.url.params["a"] == "commit"
        assert request.url.params["bdstoken"] == "bd-token"
        form = parse_qs(request.content.decode())
        assert form["path"] == ["/新目录"]
        assert form["isdir"] == ["1"]
        assert form["block_list"] == ["[]"]
        return httpx.Response(200, json={"errno": 0})

    BaiduAdapter(httpx.Client(transport=httpx.MockTransport(handler))).create_dir(COOKIE, "/新目录")
    _, duplicate = scripted([
        ("gettemplatevariable", {"errno": 0, "result": {"bdstoken": "bd-token"}}),
        ("api/create", {"errno": -8}),
    ])
    with pytest.raises(DuplicateName):
        BaiduAdapter(duplicate).create_dir(COOKIE, "/新目录")


def test_prepare_refreshes_a_short_login_cookie():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "gettemplatevariable" in url and "STOKEN=fresh" not in request.headers["cookie"]:
            return httpx.Response(200, json={"errno": -6})
        if "disk/home" in url:
            return httpx.Response(
                302,
                headers={"location": "https://passport.baidu.com/v3/login/api/auth/?tpl=netdisk", "set-cookie": "STOKEN=fresh; Path=/"},
            )
        if "passport.baidu.com" in url:
            return httpx.Response(302, headers={"location": "https://pan.baidu.com/disk/main"})
        if "disk/main" in url:
            return httpx.Response(200, text="ok")
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        raise AssertionError(url)

    warmed = BaiduAdapter(httpx.Client(transport=httpx.MockTransport(handler))).prepare("BDUSS=bd; STOKEN=old")
    assert "BDUSS=bd" in warmed
    assert "STOKEN=fresh" in warmed


def test_transfer_saves_every_root_entry():
    calls, client = scripted([
        ("gettemplatevariable", {"errno": 0, "result": {"bdstoken": "bd-token"}}),
        ("share/verify", {"errno": 0, "randsk": "rand-sk"}),
        ("share/list", {"errno": 0, "share_id": 9, "uk": 8, "list": [
            {"fs_id": 11}, {"fs_id": 12},
        ]}),
        ("share/transfer", {"errno": 0}),
    ])
    BaiduAdapter(client).transfer_share(COOKIE, "AbCdEf", "ab12", "/来自转存")
    assert calls["n"] == 4
    assert all(COOKIE not in url for url in calls["urls"])


def test_transfer_keeps_the_share_secret_encoded():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        if "share/verify" in url:
            return httpx.Response(200, json={"errno": 0, "randsk": "a%2Bb%3D"})
        if "share/list" in url:
            assert "BDCLND=a%2Bb%3D" in request.headers["cookie"]
            assert "BDCLND=a+b=" not in request.headers["cookie"]
            return httpx.Response(200, json={"errno": 0, "share_id": 9, "uk": 8, "list": [{"fs_id": "11"}]})
        if "share/transfer" in url:
            assert "sekey=a%2Bb%3D" in str(request.url)
            assert "sekey=a%252B" not in str(request.url)
            return httpx.Response(200, json={"errno": 0})
        raise AssertionError(url)

    BaiduAdapter(httpx.Client(transport=httpx.MockTransport(handler))).transfer_share(
        COOKIE, "AbCdEf", "ab12", "/来自转存"
    )


def test_transfer_accepts_string_file_ids():
    calls, client = scripted([
        ("gettemplatevariable", {"errno": 0, "result": {"bdstoken": "bd-token"}}),
        ("share/verify", {"errno": 0, "randsk": "rand-sk"}),
        ("share/list", {"errno": 0, "share_id": "9", "uk": "8", "list": [{"fs_id": "11"}, {"fs_id": "12"}]}),
        ("share/transfer", {"errno": 0}),
    ])
    BaiduAdapter(client).transfer_share(COOKIE, "AbCdEf", "ab12", "/来自转存")
    assert calls["n"] == 4


def test_transfer_replaces_an_older_share_cookie():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        if "share/verify" in url:
            return httpx.Response(200, json={"errno": 0, "randsk": "new-sk"})
        if "share/list" in url:
            cookie = request.headers["cookie"]
            assert cookie.count("BDCLND=") == 1
            assert "BDCLND=new-sk" in cookie
            assert "old-sk" not in cookie
            return httpx.Response(200, json={"errno": 0, "share_id": 9, "uk": 8, "list": [{"fs_id": 11}]})
        if "share/transfer" in url:
            return httpx.Response(200, json={"errno": 0})
        raise AssertionError(url)

    BaiduAdapter(httpx.Client(transport=httpx.MockTransport(handler))).transfer_share(
        "BDUSS=bd; BDCLND=old-sk", "AbCdEf", "ab12", "/来自转存"
    )


def test_transfer_error_mapping():
    def once(kind, payload, exc):
        _, client = scripted([
            ("gettemplatevariable", {"errno": 0, "result": {"bdstoken": "bd-token"}}),
            (kind, payload),
        ])
        with pytest.raises(exc):
            BaiduAdapter(client).transfer_share(COOKIE, "AbCdEf", "ab12", "/来自转存")

    once("share/verify", {"errno": -12}, WrongPassword)
    once("share/verify", {"errno": 116}, InvalidLink)
    once("share/verify", {"errno": 31034}, RateLimited)
    _, client = scripted([
        ("gettemplatevariable", {"errno": 0, "result": {"bdstoken": "bd-token"}}),
        ("share/verify", {"errno": 0, "randsk": "rand-sk"}),
        ("share/list", {"errno": 0, "share_id": 9, "uk": 8, "list": [{"fs_id": 11}, {"fs_id": 12}]}),
        ("share/transfer", {"errno": -33}),
    ])
    with pytest.raises(DuplicateName):
        BaiduAdapter(client).transfer_share(COOKIE, "AbCdEf", None, "/来自转存")


def test_rename_delete_and_share_use_file_manager():
    from urllib.parse import parse_qs

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        form = parse_qs(request.content.decode())
        if "filemanager" in url and request.url.params["opera"] == "rename":
            assert json.loads(form["filelist"][0]) == [{"path": "/说明.txt", "newname": "新说明.txt"}]
            return httpx.Response(200, json={"errno": 0})
        if "filemanager" in url and request.url.params["opera"] == "delete":
            assert json.loads(form["filelist"][0]) == ["/说明.txt"]
            return httpx.Response(200, json={"errno": 0})
        if "share/set" in url:
            assert json.loads(form["fid_list"][0]) == [42]
            assert form["period"] == ["0"]
            assert len(form["pwd"][0]) == 4
            return httpx.Response(200, json={"errno": 0, "link": "https://pan.baidu.com/s/1AbCdEf"})
        raise AssertionError(url)

    adapter = BaiduAdapter(httpx.Client(transport=httpx.MockTransport(handler)))
    adapter.rename(COOKIE, "/说明.txt", "新说明.txt")
    adapter.delete(COOKIE, "/说明.txt")
    link = adapter.create_share(COOKIE, 42, "ab12")
    assert link == "https://pan.baidu.com/s/1AbCdEf?pwd=ab12"


def test_copy_uses_file_manager():
    from urllib.parse import parse_qs

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        form = parse_qs(request.content.decode())
        if "filemanager" in url and request.url.params["opera"] == "copy":
            assert json.loads(form["filelist"][0]) == [
                {"path": "/说明.txt", "dest": "/目标", "newname": "说明.txt"}
            ]
            return httpx.Response(200, json={"errno": 0})
        raise AssertionError(url)

    adapter = BaiduAdapter(httpx.Client(transport=httpx.MockTransport(handler)))
    adapter.copy(COOKIE, "/说明.txt", "/目标", "说明.txt")


def test_copy_duplicate_raises():
    from urllib.parse import parse_qs

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        if "filemanager" in url and request.url.params["opera"] == "copy":
            parse_qs(request.content.decode())
            return httpx.Response(200, json={"errno": -33})
        raise AssertionError(url)

    adapter = BaiduAdapter(httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(DuplicateName):
        adapter.copy(COOKIE, "/说明.txt", "/目标", "说明.txt")


def test_download_url_rejects_a_folder_and_streams_a_file():
    from app.pans.baidu import PCS_UA

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"] == PCS_UA
        assert COOKIE in request.headers["cookie"]
        if "locatedownload" in str(request.url) and request.url.params["path"] == "/毕业照":
            return httpx.Response(403, json={"error_code": 31074})
        if "locatedownload" in str(request.url):
            return httpx.Response(200, json={"urls": [{"url": "https://d.pcs.baidu.com/file/abc"}]})
        assert request.url.host == "d.pcs.baidu.com"
        return httpx.Response(200, content=b"hello-file")

    adapter = BaiduAdapter(httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(NotAFile):
        adapter.open_download(COOKIE, "/毕业照")
    assert b"".join(adapter.open_download(COOKIE, "/说明.txt")) == b"hello-file"


def test_download_skips_a_forbidden_node():
    from app.pans.baidu import DOWNLOAD_CHUNK

    def handler(request: httpx.Request) -> httpx.Response:
        if "locatedownload" in str(request.url):
            return httpx.Response(200, json={"urls": [
                {"url": "https://a.baidupcs.com/file/one"},
                {"url": "https://b.baidupcs.com/file/two"},
            ]})
        if request.url.host.startswith("a."):
            return httpx.Response(403, content=b'{"error_code":31326}')
        assert request.headers["range"] == f"bytes=0-{DOWNLOAD_CHUNK - 1}"
        return httpx.Response(206, content=b"pdf", headers={"Content-Range": "bytes 0-2/3"})

    adapter = BaiduAdapter(httpx.Client(transport=httpx.MockTransport(handler)))
    assert b"".join(adapter.open_download(COOKIE, "/说明.txt")) == b"pdf"


def test_download_url_rejects_an_outside_host():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"urls": [{"url": "https://evil.example/file"}]})

    adapter = BaiduAdapter(httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(TransferFailed):
        adapter.open_download(COOKIE, "/说明.txt")
