from sqlalchemy import select

from app.core.crypto import encrypt_cookie
from app.models import LibraryItem, PanAccount, User
from app.services.library import parse_folder_label
from app.services.library_sync import sync_episodes

KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
COOKIE = "BDUSS=library-sync-cookie"


def register(client, email="library-sync@example.com"):
    response = client.post("/api/auth/register", json={"email": email, "password": "password-123"})
    assert response.status_code == 201


def bind(client, email="library-sync@example.com", provider="baidu", nickname="同步账号"):
    with client.app.state.session_factory() as session:
        user = session.scalars(select(User).where(User.email == email)).one()
        account = PanAccount(
            user_id=user.id,
            provider=provider,
            nickname=nickname,
            cookie_ciphertext=encrypt_cookie(COOKIE, KEY),
            status="valid",
        )
        session.add(account)
        session.commit()
        return account.id, user.id


def seed_item(client, user_id: int, *, prefix: str, name: str, finished: bool = False, latest: int | None = None):
    with client.app.state.session_factory() as session:
        item = LibraryItem(
            user_id=user_id,
            prefix=prefix,
            name=name,
            finished=finished,
            latest_episode=latest,
            quark_url="",
            baidu_url="https://pan.baidu.com/s/1x",
            xunlei_url="",
        )
        session.add(item)
        session.commit()
        return item.id


def test_parse_folder_label_variants():
    assert parse_folder_label("009 朝朝入梦#59") == ("009", "朝朝入梦", False, 59)
    assert parse_folder_label("010 朝云潜行#完结") == ("010", "朝云潜行", True, None)
    assert parse_folder_label("020 测试#完结#59") == ("020", "测试", True, 59)
    assert parse_folder_label("007 旧格式｜完结｜100") == ("007", "旧格式", True, 100)
    assert parse_folder_label("没有前缀") is None


def test_settings_library_sync_sources_roundtrip(client):
    register(client)
    account_id, _user_id = bind(client)
    empty = client.get("/api/settings/library-sync-sources")
    assert empty.status_code == 200
    assert empty.json() == []

    saved = client.put(
        "/api/settings/library-sync-sources",
        json={
            "sources": [
                {"account_id": account_id, "directory": "/漫剧", "label": "根目录 / 漫剧", "sort_order": 0},
            ]
        },
    )
    assert saved.status_code == 200
    body = saved.json()
    assert len(body) == 1
    assert body[0]["account_id"] == account_id
    assert body[0]["directory"] == "/漫剧"
    assert body[0]["label"] == "根目录 / 漫剧"

    cleared = client.put("/api/settings/library-sync-sources", json={"sources": []})
    assert cleared.status_code == 200
    assert cleared.json() == []


def test_sync_episodes_updates_only_matched_progress(client):
    register(client)
    account_id, user_id = bind(client)
    seed_item(client, user_id, prefix="009", name="朝朝入梦", finished=False, latest=10)
    seed_item(client, user_id, prefix="010", name="朝云潜行", finished=False, latest=None)
    seed_item(client, user_id, prefix="099", name="未出现", finished=False, latest=1)

    saved = client.put(
        "/api/settings/library-sync-sources",
        json={"sources": [{"account_id": account_id, "directory": "/漫剧", "label": "漫剧", "sort_order": 0}]},
    )
    assert saved.status_code == 200

    folders = {
        account_id: {
            "/漫剧": [
                "009 朝朝入梦#59",
                "010 朝云潜行#完结",
                "088 网盘有库没有#12",
                "普通文件夹",
            ]
        }
    }

    with client.app.state.session_factory() as session:
        result = sync_episodes(
            session,
            user_id,
            list_folders=lambda aid, directory: folders.get(aid, {}).get(directory, []),
        )
        session.commit()

    assert result.updated == 2
    assert result.unchanged == 0
    assert result.unmatched == 1
    by_prefix = {hit.prefix: hit for hit in result.items}
    assert by_prefix["009"].finished is False
    assert by_prefix["009"].latest_episode == 59
    assert by_prefix["009"].changed is True
    assert by_prefix["010"].finished is True
    assert by_prefix["010"].latest_episode is None

    listed = client.get("/api/library")
    rows = {item["prefix"]: item for item in listed.json()}
    assert rows["009"]["latest_episode"] == 59
    assert rows["009"]["previous_episode"] == 10
    assert rows["010"]["finished"] is True
    assert rows["010"]["previous_episode"] is None
    assert rows["099"]["latest_episode"] == 1


def test_sync_episodes_keeps_previous_when_latest_changes_again(client):
    register(client, email="library-sync-prev@example.com")
    account_id, user_id = bind(client, email="library-sync-prev@example.com")
    seed_item(client, user_id, prefix="001", name="连载", finished=False, latest=5)

    assert (
        client.put(
            "/api/settings/library-sync-sources",
            json={"sources": [{"account_id": account_id, "directory": "/剧", "label": "剧", "sort_order": 0}]},
        ).status_code
        == 200
    )

    folders = {account_id: {"/剧": ["001 连载#8"]}}
    with client.app.state.session_factory() as session:
        sync_episodes(
            session,
            user_id,
            list_folders=lambda aid, directory: folders.get(aid, {}).get(directory, []),
        )
        session.commit()

    first = {item["prefix"]: item for item in client.get("/api/library").json()}
    assert first["001"]["latest_episode"] == 8
    assert first["001"]["previous_episode"] == 5

    folders = {account_id: {"/剧": ["001 连载#12"]}}
    with client.app.state.session_factory() as session:
        sync_episodes(
            session,
            user_id,
            list_folders=lambda aid, directory: folders.get(aid, {}).get(directory, []),
        )
        session.commit()

    second = {item["prefix"]: item for item in client.get("/api/library").json()}
    assert second["001"]["latest_episode"] == 12
    assert second["001"]["previous_episode"] == 8


def test_sync_episodes_later_source_wins(client):
    register(client, email="library-sync-order@example.com")
    first_id, user_id = bind(client, email="library-sync-order@example.com", nickname="一号")
    second_id, _ = bind(client, email="library-sync-order@example.com", nickname="二号")
    seed_item(client, user_id, prefix="001", name="同号", finished=False, latest=1)

    assert (
        client.put(
            "/api/settings/library-sync-sources",
            json={
                "sources": [
                    {"account_id": first_id, "directory": "/A", "label": "A", "sort_order": 0},
                    {"account_id": second_id, "directory": "/B", "label": "B", "sort_order": 1},
                ]
            },
        ).status_code
        == 200
    )

    folders = {
        first_id: {"/A": ["001 同号#10"]},
        second_id: {"/B": ["001 同号#完结#20"]},
    }

    with client.app.state.session_factory() as session:
        result = sync_episodes(
            session,
            user_id,
            list_folders=lambda aid, directory: folders.get(aid, {}).get(directory, []),
        )
        session.commit()

    assert result.updated == 1
    assert result.items[0].finished is True
    assert result.items[0].latest_episode == 20


def test_sync_episodes_requires_sources(client):
    register(client, email="library-sync-empty@example.com")
    response = client.post("/api/library/sync-episodes")
    assert response.status_code == 422
    assert "同步目录" in response.json()["detail"]
