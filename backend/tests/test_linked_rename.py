from app.core.crypto import encrypt_cookie
from app.models import LibraryItem, PanAccount, User
from app.services.linked_rename import LinkedRenameResult, MemberDraft, linked_rename, prefix_key, replace_members
from sqlalchemy import select

KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
COOKIE = "BDUSS=linked-rename-cookie"


def register(client, email="linked-rename@example.com"):
    response = client.post("/api/auth/register", json={"email": email, "password": "password-123"})
    assert response.status_code == 201


def bind(client, email="linked-rename@example.com", provider="baidu", nickname="主账号"):
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


def test_prefix_key_matches_numeric_value():
    assert prefix_key("009 朝朝入梦#59") == 9
    assert prefix_key("9 朝朝入梦") == 9
    assert prefix_key("没有序号") is None


def test_linked_rename_settings_roundtrip(client):
    register(client)
    primary_id, _ = bind(client, nickname="主")
    peer_id, _ = bind(client, nickname="从", provider="xunlei")
    empty = client.get("/api/settings/linked-rename")
    assert empty.status_code == 200
    assert empty.json() == {"members": []}

    saved = client.put(
        "/api/settings/linked-rename",
        json={
            "members": [
                {
                    "account_id": primary_id,
                    "directory": "/漫剧",
                    "label": "主",
                    "is_primary": True,
                    "sort_order": 0,
                },
                {
                    "account_id": peer_id,
                    "directory": "/peer",
                    "label": "从",
                    "is_primary": False,
                    "sort_order": 1,
                },
            ]
        },
    )
    assert saved.status_code == 200
    body = saved.json()["members"]
    assert len(body) == 2
    assert body[0]["is_primary"] is True
    assert body[0]["directory"] == "/漫剧"
    assert body[1]["account_id"] == peer_id


def test_linked_rename_service_renames_peers_by_prefix(client):
    register(client, email="linked-svc@example.com")
    primary_id, user_id = bind(client, email="linked-svc@example.com", nickname="主")
    peer_id, _ = bind(client, email="linked-svc@example.com", nickname="从", provider="quark")
    with client.app.state.session_factory() as session:
        replace_members(
            session,
            user_id,
            [
                MemberDraft(primary_id, "/A", "主", True, 0),
                MemberDraft(peer_id, "/B", "从", False, 1),
            ],
        )
        session.commit()

    renamed: list[tuple[int, str, str]] = []
    folders = {
        peer_id: {
            "/B": [("/B/p1", "009 旧名｜10"), ("/B/p2", "010 别的")],
        }
    }

    def list_folders(account_id: int, directory: str):
        return folders.get(account_id, {}).get(directory, [])

    def rename(account_id: int, path: str, name: str):
        renamed.append((account_id, path, name))

    with client.app.state.session_factory() as session:
        result = linked_rename(
            session,
            user_id,
            account_id=primary_id,
            path="/A/src",
            current_name="009 朝朝入梦#59",
            new_name="009 朝朝入梦#60",
            list_folders=list_folders,
            rename=rename,
        )
        assert isinstance(result, LinkedRenameResult)
        assert result.renamed == 2
        assert result.skipped == 0
        assert result.failed == 0

    assert renamed == [
        (primary_id, "/A/src", "009 朝朝入梦#60"),
        (peer_id, "/B/p1", "009 朝朝入梦#60"),
    ]


def test_linked_rename_skips_missing_peer_quietly(client):
    register(client, email="linked-skip@example.com")
    primary_id, user_id = bind(client, email="linked-skip@example.com", nickname="主")
    peer_id, _ = bind(client, email="linked-skip@example.com", nickname="从", provider="quark")
    with client.app.state.session_factory() as session:
        replace_members(
            session,
            user_id,
            [
                MemberDraft(primary_id, "/A", "主", True, 0),
                MemberDraft(peer_id, "/B", "从", False, 1),
            ],
        )
        session.commit()

    renamed: list[tuple[int, str, str]] = []

    with client.app.state.session_factory() as session:
        result = linked_rename(
            session,
            user_id,
            account_id=primary_id,
            path="/A/src",
            current_name="088 只有主侧",
            new_name="088 只有主侧#1",
            list_folders=lambda aid, directory: [],
            rename=lambda aid, path, name: renamed.append((aid, path, name)),
        )

    assert result.renamed == 1
    assert result.skipped == 1
    assert result.failed == 0
    assert renamed == [(primary_id, "/A/src", "088 只有主侧#1")]


def test_linked_rename_updates_library_episode_when_changed(client):
    register(client, email="linked-lib@example.com")
    primary_id, user_id = bind(client, email="linked-lib@example.com", nickname="主")
    with client.app.state.session_factory() as session:
        replace_members(session, user_id, [MemberDraft(primary_id, "/A", "主", True, 0)])
        session.add(
            LibraryItem(
                user_id=user_id,
                prefix="009",
                name="朝朝入梦",
                finished=False,
                latest_episode=59,
                quark_url="",
                baidu_url="https://pan.baidu.com/s/1x",
                xunlei_url="",
            )
        )
        session.commit()

    with client.app.state.session_factory() as session:
        linked_rename(
            session,
            user_id,
            account_id=primary_id,
            path="/A/src",
            current_name="009 朝朝入梦#59",
            new_name="009 朝朝入梦#60",
            list_folders=lambda aid, directory: [],
            rename=lambda aid, path, name: None,
        )
        session.commit()

    with client.app.state.session_factory() as session:
        item = session.scalars(select(LibraryItem).where(LibraryItem.user_id == user_id, LibraryItem.prefix == "009")).one()
        assert item.latest_episode == 60
        assert item.previous_episode == 59
        assert item.finished is False


def test_linked_rename_skips_library_when_episode_unchanged(client):
    register(client, email="linked-lib-skip@example.com")
    primary_id, user_id = bind(client, email="linked-lib-skip@example.com", nickname="主")
    with client.app.state.session_factory() as session:
        replace_members(session, user_id, [MemberDraft(primary_id, "/A", "主", True, 0)])
        session.add(
            LibraryItem(
                user_id=user_id,
                prefix="009",
                name="朝朝入梦",
                finished=False,
                latest_episode=59,
                previous_episode=10,
                quark_url="",
                baidu_url="https://pan.baidu.com/s/1x",
                xunlei_url="",
            )
        )
        session.commit()

    with client.app.state.session_factory() as session:
        linked_rename(
            session,
            user_id,
            account_id=primary_id,
            path="/A/src",
            current_name="009 朝朝入梦#59",
            new_name="009 朝朝入梦改名#59",
            list_folders=lambda aid, directory: [],
            rename=lambda aid, path, name: None,
        )
        session.commit()

    with client.app.state.session_factory() as session:
        item = session.scalars(select(LibraryItem).where(LibraryItem.user_id == user_id, LibraryItem.prefix == "009")).one()
        assert item.latest_episode == 59
        assert item.previous_episode == 10
        assert item.name == "朝朝入梦"
