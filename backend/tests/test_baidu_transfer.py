import json

import httpx
import pytest

from app.pans.baidu import BaiduAdapter
from app.pans.errors import DuplicateName, InvalidLink, LoginRejected, PathNotFound, RateLimited, WrongPassword

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
            {"server_filename": "说明.txt", "path": "/说明.txt", "isdir": 0},
        ]}),
    ])
    entries = BaiduAdapter(client).list_dir(COOKIE, "/")
    assert [(item.name, item.path, item.is_dir) for item in entries] == [
        ("片子", "/片子", True),
        ("说明.txt", "/说明.txt", False),
    ]
    assert calls["n"] == 1


def test_missing_directory_and_bad_login():
    _, missing = scripted([("xpan/file", {"errno": -9})])
    with pytest.raises(PathNotFound):
        BaiduAdapter(missing).list_dir(COOKIE, "/没有")
    _, signed_out = scripted([("xpan/file", {"errno": -6})])
    with pytest.raises(LoginRejected):
        BaiduAdapter(signed_out).list_dir(COOKIE, "/没有")


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
