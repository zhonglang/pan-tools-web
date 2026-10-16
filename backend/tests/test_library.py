from app.models import User
from sqlalchemy import select


def register(client, email="library@example.com"):
    response = client.post("/api/auth/register", json={"email": email, "password": "password-123"})
    assert response.status_code == 201


def test_same_prefix_from_three_exports_becomes_one_drama(client):
    register(client)
    imported = client.post("/api/library/import", json={"rows": [
        {"name": "001 《回乡》【1-42】", "url": "https://pan.quark.cn/s/quark001", "password": "ab12"},
        {"name": "004 黑化虫虫【更至 18】", "url": "https://pan.baidu.com/s/1baidu004", "password": "cd34"},
        {"name": "001 回乡", "url": "https://pan.xunlei.com/s/xl001?pwd=g298#", "password": "g298"},
        {"name": "001 《回乡》夸克名", "url": "https://pan.baidu.com/s/1baidu001", "password": ""},
    ]})
    assert imported.status_code == 200
    body = imported.json()
    assert body["created"] == 2
    assert body["updated"] == 0
    assert body["skipped"] == 0
    by_prefix = {item["prefix"]: item for item in body["items"]}
    assert list(by_prefix) == ["001", "004"]
    assert by_prefix["001"]["name"] == "《回乡》【1-42】"
    assert by_prefix["001"]["quark_url"] == "https://pan.quark.cn/s/quark001 提取码: ab12"
    assert by_prefix["001"]["xunlei_url"] == "https://pan.xunlei.com/s/xl001?pwd=g298#"
    assert by_prefix["001"]["baidu_url"] == "https://pan.baidu.com/s/1baidu001"
    assert by_prefix["004"]["baidu_url"] == "https://pan.baidu.com/s/1baidu004 提取码: cd34"
    assert by_prefix["004"]["quark_url"] == ""


def test_numeric_prefix_keeps_width_and_sorts_by_value(client):
    register(client)
    imported = client.post("/api/library/import", json={"rows": [
        {"name": "10 十", "url": "https://pan.baidu.com/s/1ten", "password": ""},
        {"name": "2 二", "url": "https://pan.baidu.com/s/1two", "password": ""},
        {"name": "001 一", "url": "https://pan.quark.cn/s/one", "password": ""},
    ]})
    assert [item["prefix"] for item in imported.json()["items"]] == ["001", "2", "10"]


def test_rows_without_a_prefix_or_pan_link_are_skipped(client):
    register(client)
    imported = client.post("/api/library/import", json={"rows": [
        {"name": "没有数字", "url": "https://pan.baidu.com/s/1plain", "password": ""},
        {"name": "003 缺链接", "url": "", "password": ""},
        {"name": "003 外链", "url": "https://example.com/s/1", "password": ""},
        {"name": "003 夸克", "url": "https://pan.quark.cn/s/ok003", "password": "zzzz"},
    ]})
    body = imported.json()
    assert body["created"] == 1
    assert body["skipped"] == 3
    assert body["items"][0]["quark_url"] == "https://pan.quark.cn/s/ok003 提取码: zzzz"


def test_later_import_updates_the_link_and_keeps_the_name(client):
    register(client)
    first = client.post("/api/library/import", json={"rows": [
        {"name": "008 原来的名字", "url": "https://pan.baidu.com/s/1old", "password": "old1"},
    ]})
    item_id = first.json()["items"][0]["id"]
    edited = client.patch(f"/api/library/{item_id}", json={
        "name": "手改的名字",
        "xunlei_url": "",
        "quark_url": "https://pan.quark.cn/s/kept",
        "baidu_url": "https://pan.baidu.com/s/1old 提取码: old1",
    })
    assert edited.status_code == 200
    assert edited.json()["name"] == "手改的名字"
    second = client.post("/api/library/import", json={"rows": [
        {"name": "008 新导出的名字", "url": "https://pan.baidu.com/s/1new", "password": "new2"},
        {"name": "008 迅雷名", "url": "https://pan.xunlei.com/s/xl008?pwd=abcd#", "password": "abcd"},
    ]})
    body = second.json()
    assert body["created"] == 0
    assert body["updated"] == 1
    item = body["items"][0]
    assert item["name"] == "手改的名字"
    assert item["quark_url"] == "https://pan.quark.cn/s/kept"
    assert item["baidu_url"] == "https://pan.baidu.com/s/1new 提取码: new2"
    assert item["xunlei_url"] == "https://pan.xunlei.com/s/xl008?pwd=abcd#"


def test_library_is_private_to_the_owner(client):
    register(client, "owner@example.com")
    created = client.post("/api/library/import", json={"rows": [
        {"name": "001 只有我", "url": "https://pan.baidu.com/s/1mine", "password": ""},
    ]})
    item_id = created.json()["items"][0]["id"]
    client.post("/api/auth/logout")
    register(client, "other@example.com")
    assert client.get("/api/library").json() == []
    denied = client.patch(f"/api/library/{item_id}", json={
        "name": "改掉",
        "xunlei_url": "",
        "quark_url": "",
        "baidu_url": "",
    })
    assert denied.status_code == 404
    client.post("/api/auth/logout")
    logged = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "password-123"})
    assert logged.status_code == 200
    assert client.get("/api/library").json()[0]["name"] == "只有我"


def test_owner_can_delete_a_library_item(client):
    register(client)
    created = client.post("/api/library/import", json={"rows": [
        {"name": "001 待删除", "url": "https://pan.baidu.com/s/1gone", "password": ""},
        {"name": "002 留下", "url": "https://pan.quark.cn/s/stay", "password": ""},
    ]})
    item_id = next(item["id"] for item in created.json()["items"] if item["prefix"] == "001")
    deleted = client.delete(f"/api/library/{item_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}
    remaining = client.get("/api/library").json()
    assert [item["prefix"] for item in remaining] == ["002"]
    missing = client.delete(f"/api/library/{item_id}")
    assert missing.status_code == 404


def test_another_user_cannot_delete_a_library_item(client):
    register(client, "owner-delete@example.com")
    created = client.post("/api/library/import", json={"rows": [
        {"name": "003 别人的", "url": "https://pan.baidu.com/s/1other", "password": ""},
    ]})
    item_id = created.json()["items"][0]["id"]
    client.post("/api/auth/logout")
    register(client, "other-delete@example.com")
    denied = client.delete(f"/api/library/{item_id}")
    assert denied.status_code == 404
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "owner-delete@example.com", "password": "password-123"})
    assert client.get("/api/library").json()[0]["name"] == "别人的"


def test_create_library_item(client):
    register(client, "create@example.com")
    created = client.post("/api/library", json={
        "prefix": "9",
        "name": "夏日妄想",
        "quark_url": "",
        "baidu_url": "https://pan.baidu.com/s/1summer",
        "xunlei_url": "",
    })
    assert created.status_code == 201
    body = created.json()
    assert body["prefix"] == "9"
    assert body["name"] == "夏日妄想"
    assert body["baidu_url"] == "https://pan.baidu.com/s/1summer"
    assert body["quark_url"] == ""
    listed = client.get("/api/library").json()
    assert [item["prefix"] for item in listed] == ["9"]


def test_create_library_item_rejects_duplicate_prefix(client):
    register(client, "dup@example.com")
    first = client.post("/api/library", json={
        "prefix": "001",
        "name": "一部",
        "quark_url": "https://pan.quark.cn/s/one",
        "baidu_url": "",
        "xunlei_url": "",
    })
    assert first.status_code == 201
    again = client.post("/api/library", json={
        "prefix": "001",
        "name": "另一部",
        "quark_url": "",
        "baidu_url": "https://pan.baidu.com/s/1two",
        "xunlei_url": "",
    })
    assert again.status_code == 422
    assert again.json()["detail"] == "编号已存在"


def test_create_library_item_requires_a_pan_link(client):
    register(client, "nolink@example.com")
    response = client.post("/api/library", json={
        "prefix": "2",
        "name": "空链接",
        "quark_url": "",
        "baidu_url": "",
        "xunlei_url": "",
    })
    assert response.status_code == 422
    assert response.json()["detail"] == "至少填写一条网盘链接"


def test_library_requires_login(client):
    assert client.get("/api/library").status_code == 401


def test_library_rows_belong_to_the_registered_user(client):
    register(client)
    client.post("/api/library/import", json={"rows": [
        {"name": "001 归属", "url": "https://pan.baidu.com/s/1owner", "password": ""},
    ]})
    with client.app.state.session_factory() as session:
        user = session.scalars(select(User).where(User.email == "library@example.com")).one()
        from app.models.library import LibraryItem

        item = session.scalars(select(LibraryItem)).one()
        assert item.user_id == user.id
