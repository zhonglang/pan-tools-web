from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.core.crypto import encrypt_cookie
from app.models import AccountStatDay, Job, PanAccount, ShareLink, ShareStatSnapshot, User
from app.services.stats import apply_share_records, date_bounds, enqueue_daily_syncs, execute_sync, query_stats, range_bounds
from tests.test_transfers import COOKIE, KEY

NOW = datetime(2026, 9, 22, 4, 0, tzinfo=timezone.utc)  # 上海 12:00
BEFORE = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)  # 上海前一天 23:00
INSIDE_EARLY = datetime(2026, 9, 22, 1, 0, tzinfo=timezone.utc)  # 上海 09:00
INSIDE_LATE = datetime(2026, 9, 22, 3, 0, tzinfo=timezone.utc)  # 上海 11:00


def register(client, email="stats@example.com", plan="paid"):
    response = client.post("/api/auth/register", json={"email": email, "password": "password-123"})
    assert response.status_code == 201
    with client.app.state.session_factory() as session:
        user = session.scalars(select(User).where(User.email == email)).one()
        if plan == "paid":
            user.plan = "paid"
            user.plan_expires_at = NOW + timedelta(days=30)
        account = PanAccount(
            user_id=user.id,
            provider="baidu",
            nickname="网盘昵称",
            cookie_ciphertext=encrypt_cookie(COOKIE, KEY),
            status="valid",
        )
        session.add(account)
        session.commit()
        return user.id, account.id


def test_free_user_cannot_query_stats(client):
    _, account_id = register(client, plan="free")
    response = client.get(f"/api/accounts/{account_id}/stats")
    assert response.status_code == 403
    created = client.get("/api/stats", params={"start": "2026-09-22", "end": "2026-09-22"})
    assert created.status_code == 403


def test_created_shares_endpoint_removed(client):
    register(client)
    response = client.get("/api/stats/created", params={"start": "2026-09-22", "end": "2026-09-22"})
    assert response.status_code == 404


def test_failed_page_keeps_old_shares_and_skips_snapshot(client):
    user_id, account_id = register(client)
    with client.app.state.session_factory() as session:
        share = ShareLink(
            user_id=user_id,
            account_id=account_id,
            baidu_share_id="9",
            name="旧文件",
            path="/旧文件",
            url="https://pan.baidu.com/s/1old",
            password="ab12",
            status="active",
            transfer_count=3,
            created_at=BEFORE,
        )
        session.add(share)
        session.flush()
        session.add(ShareStatSnapshot(share_link_id=share.id, account_id=account_id, transfer_count=3, view_count=1, download_count=0, taken_at=BEFORE))
        job = Job(user_id=user_id, account_id=account_id, type="sync", status="pending", directory="/", created_at=NOW, updated_at=NOW)
        session.add(job)
        session.commit()
        share_id, job_id = share.id, job.id

    def handler(request: httpx.Request) -> httpx.Response:
        if "gettemplatevariable" in str(request.url):
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        page = int(request.url.params["page"])
        if page == 1:
            return httpx.Response(200, json={"errno": 0, "list": [{"shareId": 9, "shorturl": "1old", "typicalPath": "/旧文件", "ctime": 1, "vCnt": 1, "tCnt": 4, "dCnt": 0}] * 100})
        return httpx.Response(200, json={"errno": 2})

    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))
    with client.app.state.session_factory() as session:
        execute_sync(session, client.app.state.pan_http_client, session.get(Job, job_id), lambda _seconds: None, NOW)
        session.commit()
        assert session.get(Job, job_id).status == "failed"
        assert session.get(ShareLink, share_id).name == "旧文件"
        assert session.get(ShareLink, share_id).password == "ab12"
        assert len(session.scalars(select(ShareStatSnapshot)).all()) == 1


def test_sync_updates_records_and_marks_missing_removed(client):
    user_id, account_id = register(client, email="sync@example.com")
    with client.app.state.session_factory() as session:
        kept = ShareLink(
            user_id=user_id,
            account_id=account_id,
            baidu_share_id="AbCd",
            name="旧名",
            path="/旧名",
            url="https://pan.baidu.com/s/1AbCd",
            password="zz99",
            status="active",
            created_at=BEFORE,
        )
        gone = ShareLink(
            user_id=user_id,
            account_id=account_id,
            baidu_share_id="8",
            name="已删",
            path="/已删",
            url="https://pan.baidu.com/s/1gone",
            status="active",
            created_at=BEFORE,
        )
        session.add_all([kept, gone])
        job = Job(user_id=user_id, account_id=account_id, type="sync", status="pending", directory="/", created_at=NOW, updated_at=NOW)
        session.add(job)
        session.commit()
        job_id = job.id

    def handler(request: httpx.Request) -> httpx.Response:
        if "gettemplatevariable" in str(request.url):
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        return httpx.Response(200, json={"errno": 0, "list": [
            {"shareId": 11, "shorturl": "1AbCd", "typicalPath": "/片子/新名", "ctime": 1_700_000_000, "expiredTime": 0, "vCnt": 5, "tCnt": 2, "dCnt": 1},
            {"shareId": 12, "shorturl": "1New", "typicalPath": "/历史", "ctime": 1_700_000_100, "expiredTime": 10, "tCnt": 7},
        ]})

    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))
    with client.app.state.session_factory() as session:
        execute_sync(session, client.app.state.pan_http_client, session.get(Job, job_id), lambda _seconds: None, NOW)
        session.commit()
        rows = session.scalars(select(ShareLink).where(ShareLink.account_id == account_id)).all()
        by_id = {row.baidu_share_id: row for row in rows}
        assert by_id["11"].password == "zz99"
        assert by_id["11"].name == "新名"
        assert by_id["8"].status == "removed"
        assert by_id["12"].expired is True
        assert by_id["12"].view_count is None
        assert session.get(Job, job_id).status == "succeeded"
        assert len(session.scalars(select(ShareStatSnapshot).where(ShareStatSnapshot.account_id == account_id)).all()) == 2


def test_same_day_refresh_updates_the_daily_snapshot(client):
    user_id, account_id = register(client, email="daily-shot@example.com")
    record = {"shareId": 21, "shorturl": "1Day", "typicalPath": "/当天", "ctime": 1_700_000_000, "vCnt": 1, "tCnt": 2, "dCnt": 0}
    later = {"shareId": 21, "shorturl": "1Day", "typicalPath": "/当天", "ctime": 1_700_000_000, "vCnt": 4, "tCnt": 9, "dCnt": 1}
    with client.app.state.session_factory() as session:
        account = session.get(PanAccount, account_id)
        apply_share_records(session, account, [record], NOW)
        apply_share_records(session, account, [later], NOW + timedelta(hours=2))
        session.commit()
        shots = session.scalars(select(ShareStatSnapshot).where(ShareStatSnapshot.account_id == account_id)).all()
        assert len(shots) == 1
        assert shots[0].transfer_count == 9
        assert shots[0].view_count == 4
        next_day = NOW + timedelta(days=1)
        apply_share_records(session, account, [later], next_day)
        session.commit()
        shots = session.scalars(select(ShareStatSnapshot).where(ShareStatSnapshot.account_id == account_id).order_by(ShareStatSnapshot.taken_at)).all()
        assert len(shots) == 2
        assert shots[1].taken_at.replace(tzinfo=None) == next_day.replace(tzinfo=None)


def test_sync_upserts_account_stat_day(client):
    user_id, account_id = register(client, email="account-day@example.com")
    first = {"shareId": 31, "shorturl": "1DayA", "typicalPath": "/日表", "ctime": 1_700_000_000, "vCnt": 1, "tCnt": 5, "dCnt": 0}
    second = {"shareId": 31, "shorturl": "1DayA", "typicalPath": "/日表", "ctime": 1_700_000_000, "vCnt": 2, "tCnt": 8, "dCnt": 1}
    with client.app.state.session_factory() as session:
        account = session.get(PanAccount, account_id)
        apply_share_records(session, account, [first], NOW)
        session.commit()
        days = session.scalars(select(AccountStatDay).where(AccountStatDay.account_id == account_id)).all()
        assert len(days) == 1
        assert days[0].transfer_total == 5
        assert days[0].view_total == 1
        assert days[0].download_total == 0
        assert days[0].link_total == 1
        apply_share_records(session, account, [second], NOW + timedelta(hours=3))
        session.commit()
        days = session.scalars(select(AccountStatDay).where(AccountStatDay.account_id == account_id)).all()
        assert len(days) == 1
        assert days[0].transfer_total == 8
        assert days[0].view_total == 2
        assert days[0].download_total == 1


def test_history_stats_filters_by_name(client):
    user_id, account_id = register(client, email="name-filter@example.com")
    with client.app.state.session_factory() as session:
        session.add_all(
            [
                ShareLink(
                    user_id=user_id,
                    account_id=account_id,
                    baidu_share_id="a",
                    name="春晚合集",
                    path="/春晚",
                    url="https://pan.baidu.com/s/1spring",
                    status="active",
                    transfer_count=3,
                    created_at=NOW,
                ),
                ShareLink(
                    user_id=user_id,
                    account_id=account_id,
                    baidu_share_id="b",
                    name="纪录片",
                    path="/纪",
                    url="https://pan.baidu.com/s/1doc",
                    status="active",
                    transfer_count=9,
                    created_at=NOW,
                ),
            ]
        )
        session.commit()
    response = client.get("/api/stats", params={"name": "春晚", "page_size": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["rank_total"] == 1
    assert [row["name"] for row in body["rows"]] == ["春晚合集"]


def test_history_stats_paginates_share_links(client):
    user_id, account_id = register(client, email="history-page@example.com")
    with client.app.state.session_factory() as session:
        rows = []
        for index in range(12):
            rows.append(
                ShareLink(
                    user_id=user_id,
                    account_id=account_id,
                    baidu_share_id=f"h{index}",
                    name=f"分享{index}",
                    path=f"/分享{index}",
                    url=f"https://pan.baidu.com/s/1h{index}",
                    status="active",
                    transfer_count=12 - index if index < 11 else None,
                    created_at=NOW - timedelta(hours=index + 1),
                )
            )
        session.add_all(rows)
        session.commit()
    response = client.get("/api/stats", params={"page": 1, "page_size": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 12
    assert body["rank_total"] == 12
    assert body["rank"] == "history"
    assert len(body["rows"]) == 10
    assert body["rows"][0]["transfers"] == 12
    assert body["rows"][1]["transfers"] == 11
    assert body["dates"] == []
    assert body["transfers"]["value"] == sum(range(2, 13))
    page2 = client.get("/api/stats", params={"page": 2, "page_size": 10}).json()
    assert len(page2["rows"]) == 2
    assert page2["rows"][-1]["transfers"] is None


def test_range_summary_uses_account_stat_days(client):
    user_id, account_id = register(client, email="day-summary@example.com")
    with client.app.state.session_factory() as session:
        session.add_all(
            [
                AccountStatDay(
                    account_id=account_id,
                    stat_date=date(2026, 9, 1),
                    transfer_total=10,
                    view_total=20,
                    download_total=4,
                    link_total=2,
                    updated_at=NOW,
                ),
                AccountStatDay(
                    account_id=account_id,
                    stat_date=date(2026, 9, 10),
                    transfer_total=25,
                    view_total=35,
                    download_total=9,
                    link_total=3,
                    updated_at=NOW,
                ),
                AccountStatDay(
                    account_id=account_id,
                    stat_date=date(2026, 9, 9),
                    transfer_total=22,
                    view_total=30,
                    download_total=8,
                    link_total=3,
                    updated_at=NOW,
                ),
                ShareLink(
                    user_id=user_id,
                    account_id=account_id,
                    baidu_share_id="n0",
                    name="开始日",
                    path="/开始日",
                    url="https://pan.baidu.com/s/1start-day",
                    status="active",
                    created_at=datetime(2026, 9, 1, 4, 0, tzinfo=timezone.utc),
                ),
                ShareLink(
                    user_id=user_id,
                    account_id=account_id,
                    baidu_share_id="n1",
                    name="新建",
                    path="/新建",
                    url="https://pan.baidu.com/s/1new",
                    status="active",
                    created_at=datetime(2026, 9, 5, 4, 0, tzinfo=timezone.utc),
                ),
            ]
        )
        session.commit()
    response = client.get("/api/stats", params={"start": "2026-09-01", "end": "2026-09-10", "page": 1, "page_size": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["rank"] == "range"
    assert body["total"] == 1  # excludes start-day create on 9/1
    assert body["transfers"]["value"] == 15
    assert body["views"]["value"] == 15
    assert body["downloads"]["value"] == 5
    assert body["dates"][0] == "2026-09-01"
    assert body["dates"][-1] == "2026-09-10"
    by_kind = {line["kind"]: line["values"] for line in body["lines"]}
    assert set(by_kind) == {"delta", "total"}
    assert by_kind["total"][0] == 10
    assert by_kind["total"][8] == 22
    assert by_kind["total"][9] == 25
    assert by_kind["delta"][9] == 3


def test_range_summary_missing_day_is_none(client):
    _, account_id = register(client, email="missing-day@example.com")
    with client.app.state.session_factory() as session:
        session.add(
            AccountStatDay(
                account_id=account_id,
                stat_date=date(2026, 9, 10),
                transfer_total=25,
                view_total=35,
                download_total=9,
                link_total=3,
                updated_at=NOW,
            )
        )
        session.commit()
    response = client.get("/api/stats", params={"start": "2026-09-01", "end": "2026-09-10"})
    assert response.status_code == 200
    assert response.json()["transfers"]["value"] is None


def test_range_summary_skips_accounts_missing_day_rows(client):
    user_id, first_id = register(client, email="partial-days@example.com")
    with client.app.state.session_factory() as session:
        second = PanAccount(
            user_id=user_id,
            provider="baidu",
            nickname="乙",
            cookie_ciphertext=encrypt_cookie(COOKIE, KEY),
            status="valid",
        )
        session.add(second)
        session.flush()
        session.add_all(
            [
                AccountStatDay(
                    account_id=first_id,
                    stat_date=date(2026, 9, 1),
                    transfer_total=10,
                    view_total=10,
                    download_total=1,
                    link_total=1,
                    updated_at=NOW,
                ),
                AccountStatDay(
                    account_id=first_id,
                    stat_date=date(2026, 9, 10),
                    transfer_total=25,
                    view_total=20,
                    download_total=3,
                    link_total=1,
                    updated_at=NOW,
                ),
                AccountStatDay(
                    account_id=second.id,
                    stat_date=date(2026, 9, 10),
                    transfer_total=100,
                    view_total=100,
                    download_total=10,
                    link_total=1,
                    updated_at=NOW,
                ),
            ]
        )
        session.commit()
    response = client.get("/api/stats", params={"start": "2026-09-01", "end": "2026-09-10"})
    assert response.status_code == 200
    assert response.json()["transfers"]["value"] == 15


def test_range_rank_paginates_snapshot_deltas(client):
    user_id, account_id = register(client, email="range-rank@example.com")
    with client.app.state.session_factory() as session:
        shares = []
        for index in range(12):
            share = ShareLink(
                user_id=user_id,
                account_id=account_id,
                baidu_share_id=str(index + 1),
                name=f"分享{index}",
                path=f"/分享{index}",
                url=f"https://pan.baidu.com/s/1r{index}",
                status="active",
                transfer_count=100 - index,
                created_at=NOW - timedelta(hours=index + 1),
            )
            shares.append(share)
        session.add_all(shares)
        session.flush()
        for index, share in enumerate(shares):
            if index >= 11:
                continue
            baseline = 10 - index
            session.add(
                ShareStatSnapshot(
                    share_link_id=share.id,
                    account_id=account_id,
                    transfer_count=baseline,
                    view_count=baseline,
                    download_count=0,
                    taken_at=BEFORE,
                )
            )
            session.add(
                ShareStatSnapshot(
                    share_link_id=share.id,
                    account_id=account_id,
                    transfer_count=baseline + (20 - index),
                    view_count=baseline + 1,
                    download_count=1,
                    taken_at=INSIDE_LATE,
                )
            )
        session.add_all(
            [
                AccountStatDay(
                    account_id=account_id,
                    stat_date=date(2026, 9, 21),
                    transfer_total=50,
                    view_total=50,
                    download_total=0,
                    link_total=11,
                    updated_at=NOW,
                ),
                AccountStatDay(
                    account_id=account_id,
                    stat_date=date(2026, 9, 22),
                    transfer_total=200,
                    view_total=80,
                    download_total=12,
                    link_total=12,
                    updated_at=NOW,
                ),
            ]
        )
        session.commit()
        account = session.get(PanAccount, account_id)
        week_start, week_end = date_bounds("2026-09-21", "2026-09-22", NOW)
        page1 = query_stats(session, [account], NOW, "range", 1, week_start, week_end, page_size=10)
        page2 = query_stats(session, [account], NOW, "range", 2, week_start, week_end, page_size=10)
        week = page1
    assert page1["rank_total"] == 12
    assert len(page1["rows"]) == 10
    assert page1["rows"][0]["name"] == "分享0"
    # 转存量 = 结束日(9/22)；转存增量 = 9/22 − 9/21；浏览/下载为结束日水位
    assert page1["rows"][0]["transfers"] == 30
    assert page1["rows"][0]["transfer_delta"] == 20
    assert page1["rows"][0]["views"] == 11
    assert page1["rows"][0]["downloads"] == 1
    assert page1["rows"][1]["transfers"] == 28
    assert page1["rows"][1]["transfer_delta"] == 19
    assert len(page2["rows"]) == 2
    assert page2["rows"][-1]["transfers"] is None
    assert page2["rows"][-1]["transfer_delta"] is None
    assert week["summary"]["transfers"]["value"] == 150


def test_range_rank_new_link_delta_equals_end_stock(client):
    user_id, account_id = register(client, email="range-new-link@example.com")
    with client.app.state.session_factory() as session:
        old = ShareLink(
            user_id=user_id,
            account_id=account_id,
            baidu_share_id="old",
            name="旧分享",
            path="/旧分享",
            url="https://pan.baidu.com/s/1old",
            status="active",
            transfer_count=30,
            created_at=BEFORE - timedelta(days=2),
        )
        new = ShareLink(
            user_id=user_id,
            account_id=account_id,
            baidu_share_id="new",
            name="新分享",
            path="/新分享",
            url="https://pan.baidu.com/s/1new",
            status="active",
            transfer_count=10,
            created_at=INSIDE_EARLY,
        )
        session.add_all([old, new])
        session.flush()
        session.add_all(
            [
                ShareStatSnapshot(
                    share_link_id=old.id,
                    account_id=account_id,
                    transfer_count=20,
                    view_count=100,
                    download_count=5,
                    taken_at=BEFORE,
                ),
                ShareStatSnapshot(
                    share_link_id=old.id,
                    account_id=account_id,
                    transfer_count=30,
                    view_count=120,
                    download_count=8,
                    taken_at=INSIDE_LATE,
                ),
                ShareStatSnapshot(
                    share_link_id=new.id,
                    account_id=account_id,
                    transfer_count=10,
                    view_count=50,
                    download_count=2,
                    taken_at=INSIDE_LATE,
                ),
                AccountStatDay(
                    account_id=account_id,
                    stat_date=date(2026, 9, 21),
                    transfer_total=20,
                    view_total=100,
                    download_total=5,
                    link_total=1,
                    updated_at=NOW,
                ),
                AccountStatDay(
                    account_id=account_id,
                    stat_date=date(2026, 9, 22),
                    transfer_total=40,
                    view_total=170,
                    download_total=10,
                    link_total=2,
                    updated_at=NOW,
                ),
            ]
        )
        session.commit()
        account = session.get(PanAccount, account_id)
        start, end = date_bounds("2026-09-21", "2026-09-22", NOW)
        body = query_stats(session, [account], NOW, "range", 1, start, end, page_size=10)
    by_name = {row["name"]: row for row in body["rows"]}
    assert by_name["旧分享"]["transfers"] == 30
    assert by_name["旧分享"]["transfer_delta"] == 10
    assert by_name["旧分享"]["views"] == 120
    assert by_name["旧分享"]["downloads"] == 8
    assert by_name["新分享"]["transfers"] == 10
    assert by_name["新分享"]["transfer_delta"] == 10
    assert by_name["新分享"]["views"] == 50
    assert by_name["新分享"]["downloads"] == 2


def test_past_end_date_includes_the_whole_shanghai_day():
    start, end = date_bounds("2026-09-20", "2026-09-21", NOW)
    assert start == datetime(2026, 9, 19, 16, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 21, 15, 59, 59, tzinfo=timezone.utc)
    _, today_end = date_bounds("2026-09-22", "2026-09-22", NOW)
    assert today_end == NOW


def test_transfer_series_uses_account_stat_days(client):
    user_id, first_id = register(client, email="series@example.com")
    with client.app.state.session_factory() as session:
        second = PanAccount(
            user_id=user_id,
            provider="baidu",
            nickname="乙",
            cookie_ciphertext=encrypt_cookie(COOKIE, KEY),
            status="valid",
        )
        session.add(second)
        session.flush()
        first = session.get(PanAccount, first_id)
        first.nickname = "甲"
        for account_id, day, total in (
            (first_id, date(2026, 9, 20), 1),
            (first_id, date(2026, 9, 21), 2),
            (first_id, date(2026, 9, 22), 5),
            (second.id, date(2026, 9, 22), 1),
        ):
            session.add(
                AccountStatDay(
                    account_id=account_id,
                    stat_date=day,
                    transfer_total=total,
                    view_total=total,
                    download_total=0,
                    link_total=1,
                    updated_at=NOW,
                )
            )
        session.commit()
        accounts = [session.get(PanAccount, first_id), session.get(PanAccount, second.id)]
        start, end = range_bounds("week", NOW)
        result = query_stats(session, accounts, NOW, "range", 1, start, end)
        history = query_stats(session, accounts, NOW, "history", 1, None, None)

    assert result["series"]["dates"] == [
        "2026-09-15",
        "2026-09-16",
        "2026-09-17",
        "2026-09-18",
        "2026-09-19",
        "2026-09-20",
        "2026-09-21",
        "2026-09-22",
    ]
    by_kind = {line["kind"]: line["values"] for line in result["series"]["lines"]}
    assert by_kind["total"] == [None, None, None, None, None, 1, 2, 6]
    assert by_kind["delta"] == [None, None, None, None, None, None, 1, 4]
    assert history["series"]["dates"] == []
    assert history["series"]["lines"] == []


def test_daily_sync_skips_quark_and_xunlei(client):
    user_id, baidu_id = register(client, email="pans-sync@example.com")
    ready = datetime(2026, 9, 22, 16, 5, tzinfo=timezone.utc)
    with client.app.state.session_factory() as session:
        for provider, nickname in (("quark", "夸克"), ("xunlei", "迅雷")):
            session.add(
                PanAccount(
                    user_id=user_id,
                    provider=provider,
                    nickname=nickname,
                    cookie_ciphertext=encrypt_cookie(COOKIE, KEY),
                    status="valid",
                )
            )
        session.commit()
        enqueue_daily_syncs(session, ready)
        session.commit()
        jobs = session.scalars(select(Job).where(Job.user_id == user_id, Job.type == "sync")).all()
        assert [job.account_id for job in jobs] == [baidu_id]


def test_daily_sync_runs_once_after_five_past_midnight(client):
    _, account_id = register(client, email="daily@example.com")
    too_early = datetime(2026, 9, 22, 16, 4, tzinfo=timezone.utc)
    ready = datetime(2026, 9, 22, 16, 5, tzinfo=timezone.utc)
    with client.app.state.session_factory() as session:
        enqueue_daily_syncs(session, too_early)
        session.commit()
        assert session.scalars(select(Job).where(Job.account_id == account_id, Job.type == "sync")).all() == []
        enqueue_daily_syncs(session, ready)
        enqueue_daily_syncs(session, ready + timedelta(minutes=10))
        session.commit()
        jobs = session.scalars(select(Job).where(Job.account_id == account_id, Job.type == "sync")).all()
        assert len(jobs) == 1
        assert jobs[0].directory == "daily-close"


def test_daily_sync_does_not_run_in_the_evening(client):
    _, account_id = register(client, email="evening@example.com")
    evening = datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc)  # 上海 22:00
    with client.app.state.session_factory() as session:
        enqueue_daily_syncs(session, evening)
        session.commit()
        assert session.scalars(select(Job).where(Job.account_id == account_id, Job.type == "sync")).all() == []


def test_midnight_sync_closes_the_previous_shanghai_day(client):
    user_id, account_id = register(client, email="close@example.com")
    dawn = datetime(2026, 9, 23, 16, 5, tzinfo=timezone.utc)  # 上海 9 月 24 日 00:05
    record = {"shareId": 31, "shorturl": "1Close", "typicalPath": "/日终", "ctime": 1_700_000_000, "vCnt": 2, "tCnt": 6, "dCnt": 1}
    with client.app.state.session_factory() as session:
        job = Job(
            user_id=user_id,
            account_id=account_id,
            type="sync",
            status="pending",
            directory="daily-close",
            created_at=dawn,
            updated_at=dawn,
        )
        session.add(job)
        session.commit()
        job_id = job.id

    def handler(request: httpx.Request) -> httpx.Response:
        if "gettemplatevariable" in str(request.url):
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        return httpx.Response(200, json={"errno": 0, "list": [record]})

    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))
    with client.app.state.session_factory() as session:
        execute_sync(session, client.app.state.pan_http_client, session.get(Job, job_id), lambda _seconds: None, dawn)
        session.commit()
        shot = session.scalars(select(ShareStatSnapshot).where(ShareStatSnapshot.account_id == account_id)).one()
        taken = shot.taken_at if shot.taken_at.tzinfo else shot.taken_at.replace(tzinfo=timezone.utc)
        assert taken.astimezone(timezone(timedelta(hours=8))).date().isoformat() == "2026-09-23"
        assert shot.transfer_count == 6
