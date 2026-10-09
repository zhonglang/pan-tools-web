from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.core.crypto import encrypt_cookie
from app.models import Job, PanAccount, ShareLink, ShareStatSnapshot, User
from app.services.stats import apply_share_records, date_bounds, enqueue_daily_syncs, execute_sync, query_created_shares, query_stats, range_bounds
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
    created = client.get("/api/stats/created", params={"start": "2026-09-22", "end": "2026-09-22"})
    assert created.status_code == 403


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


def _seed_metrics(session, user_id, account_id):
    early = ShareLink(user_id=user_id, account_id=account_id, baidu_share_id="1", name="早", path="/早", url="https://pan.baidu.com/s/1early", status="active", view_count=10, transfer_count=8, download_count=4, created_at=BEFORE)
    late = ShareLink(user_id=user_id, account_id=account_id, baidu_share_id="2", name="新", path="/新", url="https://pan.baidu.com/s/1late", status="active", view_count=3, transfer_count=3, download_count=1, created_at=NOW - timedelta(hours=1))
    unknown = ShareLink(user_id=user_id, account_id=account_id, baidu_share_id="3", name="空", path="/空", url="https://pan.baidu.com/s/1none", status="active", created_at=NOW - timedelta(hours=2))
    session.add_all([early, late, unknown])
    session.flush()
    session.add(ShareStatSnapshot(share_link_id=early.id, account_id=account_id, view_count=4, transfer_count=2, download_count=1, taken_at=BEFORE))
    session.add(ShareStatSnapshot(share_link_id=late.id, account_id=account_id, view_count=1, transfer_count=1, download_count=0, taken_at=INSIDE_EARLY))
    session.add(ShareStatSnapshot(share_link_id=late.id, account_id=account_id, view_count=3, transfer_count=3, download_count=1, taken_at=INSIDE_LATE))
    session.add(ShareStatSnapshot(share_link_id=unknown.id, account_id=account_id, view_count=1, transfer_count=1, download_count=1, taken_at=INSIDE_LATE))
    session.commit()


def test_range_without_baseline_starts_from_the_earliest_snapshot(client):
    user_id, account_id = register(client, email="baseline@example.com")
    with client.app.state.session_factory() as session:
        share = ShareLink(
            user_id=user_id,
            account_id=account_id,
            baidu_share_id="4",
            name="区间",
            path="/区间",
            url="https://pan.baidu.com/s/1span",
            status="active",
            view_count=9,
            transfer_count=6,
            download_count=2,
            created_at=BEFORE,
        )
        session.add(share)
        session.flush()
        session.add(ShareStatSnapshot(share_link_id=share.id, account_id=account_id, view_count=2, transfer_count=1, download_count=0, taken_at=INSIDE_EARLY))
        session.add(ShareStatSnapshot(share_link_id=share.id, account_id=account_id, view_count=9, transfer_count=6, download_count=2, taken_at=INSIDE_LATE))
        session.commit()
        account = session.get(PanAccount, account_id)
        start, end = range_bounds("today", NOW)
        today = query_stats(session, [account], NOW, "range", 1, start, end)
    assert today["summary"]["transfers"] == {"value": 5, "from": INSIDE_EARLY}
    assert today["rows"][0]["transfers"] == 5


def test_stats_ranges_and_rankings(client):
    user_id, account_id = register(client, email="rank@example.com")
    with client.app.state.session_factory() as session:
        _seed_metrics(session, user_id, account_id)
        account = session.get(PanAccount, account_id)
        today_start, today_end = range_bounds("today", NOW)
        week_start, week_end = range_bounds("week", NOW)
        today = query_stats(session, [account], NOW, "range", 1, today_start, today_end)
        week = query_stats(session, [account], NOW, "history", 1, week_start, week_end)
    assert today["summary"]["new_shares"] == 2
    assert week["summary"]["new_shares"] == 3
    assert today["summary"]["transfers"]["value"] == (8 - 2) + (3 - 1)
    assert today["summary"]["views"]["value"] == (10 - 4) + (3 - 1)
    assert today["page_size"] == 10
    assert today["rows"][0]["name"] == "早"
    ranked = [row["url"] for row in today["rows"]]
    assert ranked[0] == "https://pan.baidu.com/s/1early"
    assert ranked[-1] == "https://pan.baidu.com/s/1none"
    history = [row["transfers"] for row in week["rows"]]
    assert history[0] == 8


def test_created_share_table_uses_live_counts_for_links_born_in_range(client):
    user_id, account_id = register(client, email="created@example.com")
    with client.app.state.session_factory() as session:
        _seed_metrics(session, user_id, account_id)
        session.add(
            ShareLink(
                user_id=user_id,
                account_id=account_id,
                baidu_share_id="8",
                name="高",
                path="/高",
                url="https://pan.baidu.com/s/1high",
                status="active",
                view_count=1,
                transfer_count=20,
                download_count=1,
                created_at=NOW - timedelta(hours=3),
            )
        )
        session.commit()
        account = session.get(PanAccount, account_id)
        start, end = date_bounds("2026-09-22", "2026-09-22", NOW)
        created = query_created_shares(session, [account], start, end, 1, 10)
    assert created["total"] == 3
    assert [row["name"] for row in created["rows"]] == ["高", "新", "空"]
    assert created["rows"][0]["transfers"] == 20
    assert created["rows"][1]["transfers"] == 3
    assert created["rows"][1]["views"] == 3
    assert created["rows"][1]["downloads"] == 1
    assert created["rows"][2]["transfers"] is None


def test_past_end_date_includes_the_whole_shanghai_day():
    start, end = date_bounds("2026-09-20", "2026-09-21", NOW)
    assert start == datetime(2026, 9, 19, 16, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 21, 15, 59, 59, tzinfo=timezone.utc)
    _, today_end = date_bounds("2026-09-22", "2026-09-22", NOW)
    assert today_end == NOW


def test_transfer_series_is_daily_per_account(client):
    user_id, first_id = register(client, email="series@example.com")
    day20 = datetime(2026, 9, 20, 4, 0, tzinfo=timezone.utc)  # 上海 12:00
    day21 = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)  # 上海 23:00
    day22 = datetime(2026, 9, 22, 3, 0, tzinfo=timezone.utc)  # 上海 11:00
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
        kept = ShareLink(
            user_id=user_id,
            account_id=first_id,
            baidu_share_id="s1",
            name="甲一",
            path="/甲一",
            url="https://pan.baidu.com/s/1series-a",
            status="active",
            transfer_count=5,
            created_at=day20,
        )
        removed = ShareLink(
            user_id=user_id,
            account_id=first_id,
            baidu_share_id="s2",
            name="甲二",
            path="/甲二",
            url="https://pan.baidu.com/s/1series-b",
            status="removed",
            transfer_count=4,
            created_at=day21,
        )
        other = ShareLink(
            user_id=user_id,
            account_id=second.id,
            baidu_share_id="s3",
            name="乙一",
            path="/乙一",
            url="https://pan.baidu.com/s/1series-c",
            status="active",
            transfer_count=1,
            created_at=day22,
        )
        session.add_all([kept, removed, other])
        session.flush()
        session.add_all([
            ShareStatSnapshot(share_link_id=kept.id, account_id=first_id, transfer_count=1, taken_at=day20),
            ShareStatSnapshot(share_link_id=kept.id, account_id=first_id, transfer_count=2, taken_at=day21),
            ShareStatSnapshot(share_link_id=kept.id, account_id=first_id, transfer_count=5, taken_at=day22),
            ShareStatSnapshot(share_link_id=removed.id, account_id=first_id, transfer_count=4, taken_at=day21),
            ShareStatSnapshot(share_link_id=removed.id, account_id=first_id, transfer_count=4, taken_at=day22),
            ShareStatSnapshot(share_link_id=other.id, account_id=second.id, transfer_count=1, taken_at=day22),
        ])
        session.commit()
        accounts = [session.get(PanAccount, first_id), session.get(PanAccount, second.id)]
        start, end = range_bounds("week", NOW)
        increment = query_stats(session, accounts, NOW, "range", 1, start, end)
        history = query_stats(session, accounts, NOW, "history", 1, start, end)

    assert increment["series"]["dates"] == [
        "2026-09-16",
        "2026-09-17",
        "2026-09-18",
        "2026-09-19",
        "2026-09-20",
        "2026-09-21",
        "2026-09-22",
    ]
    by_name = {line["account_name"]: line["values"] for line in increment["series"]["lines"]}
    assert by_name["甲"] == [None, None, None, None, None, 1, 3]
    assert by_name["乙"] == [None, None, None, None, None, None, None]
    history_by_name = {line["account_name"]: line["values"] for line in history["series"]["lines"]}
    assert history_by_name["甲"] == [None, None, None, None, 1, 6, 9]
    assert history_by_name["乙"] == [None, None, None, None, None, None, 1]


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
