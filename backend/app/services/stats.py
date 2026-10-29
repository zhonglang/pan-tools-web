from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_cookie
from app.services.transfers import keep_warmed
from app.services.membership import can_use_paid_features
from app.models import (
    AccountStatDay,
    Job,
    PanAccount,
    ShareLink,
    ShareStatSnapshot,
    User,
)
from app.pans import adapter_for
from app.pans.errors import LoginRejected, RateLimited, TransferFailed
from app.services.links import with_share_password
from app.services.transfers import EXPIRED, RETRY_DELAYS, publish

SHANGHAI = ZoneInfo("Asia/Shanghai")
PAGE_SIZE = 10
PAGE_SIZES = (10, 20, 50)
DAILY_CLOSE = "daily-close"
# 上海时间 [00:00, 00:02)：定时入队；此窗口内触发的同步（含手动）归属前一天
PREVIOUS_DAY_WINDOW_END_MINUTE = 2


def in_previous_day_window(now: datetime) -> bool:
    local = _aware(now).astimezone(SHANGHAI)
    return local.hour == 0 and local.minute < PREVIOUS_DAY_WINDOW_END_MINUTE


def date_bounds(
    start_day: str, end_day: str, now: datetime
) -> tuple[datetime, datetime]:
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    local_now = current.astimezone(SHANGHAI)
    try:
        start_on = datetime.strptime(start_day, "%Y-%m-%d").replace(tzinfo=SHANGHAI)
        end_on = datetime.strptime(end_day, "%Y-%m-%d").replace(tzinfo=SHANGHAI)
    except ValueError as error:
        raise ValueError("时间范围无效") from error
    if end_on.date() < start_on.date():
        raise ValueError("时间范围无效")
    start_at = start_on.replace(hour=0, minute=0, second=0, microsecond=0)
    if end_on.date() >= local_now.date():
        end_at = local_now
    else:
        end_at = end_on.replace(hour=23, minute=59, second=59, microsecond=0)
    if start_at > end_at:
        raise ValueError("时间范围无效")
    return start_at.astimezone(timezone.utc), end_at.astimezone(timezone.utc)


def range_bounds(span: str, now: datetime) -> tuple[datetime, datetime]:
    """Shortcuts include one extra baseline day because range cards exclude the start day."""
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    local = current.astimezone(SHANGHAI)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if span == "today":
        start -= timedelta(days=1)
    elif span == "week":
        start -= timedelta(days=7)
    elif span == "month":
        start -= timedelta(days=30)
    else:
        raise ValueError("时间范围无效")
    return start.astimezone(timezone.utc), current


def enqueue_daily_syncs(session: Session, now: datetime) -> None:
    current = _aware(now)
    if not in_previous_day_window(current):
        return
    local = current.astimezone(SHANGHAI)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(
        timezone.utc
    )
    accounts = session.scalars(
        select(PanAccount).where(
            PanAccount.provider == "baidu", PanAccount.status == "valid"
        )
    ).all()
    for account in accounts:
        user = session.get(User, account.user_id)
        if user is None or not can_use_paid_features(user, current):
            continue
        existing = session.scalar(
            select(Job).where(
                Job.account_id == account.id,
                Job.type == "sync",
                Job.directory == DAILY_CLOSE,
                Job.created_at >= day_start,
            )
        )
        if existing is not None:
            continue
        session.add(
            Job(
                user_id=account.user_id,
                account_id=account.id,
                type="sync",
                status="pending",
                directory=DAILY_CLOSE,
                created_at=current,
                updated_at=current,
            )
        )


def execute_sync(session: Session, client, job: Job, sleeper, now: datetime) -> None:
    job.status = "running"
    job.updated_at = now
    publish(session)
    account = session.get(PanAccount, job.account_id)
    if account is not None and account.provider != "baidu":
        job.status = "succeeded"
        job.error = None
        job.updated_at = now
        return
    if account is None or account.status != "valid":
        job.status = "failed"
        job.error = EXPIRED
        job.updated_at = now
        return
    cookie = decrypt_cookie(account.cookie_ciphertext, get_settings().cookie_fernet_key)
    adapter = adapter_for(account.provider, client)
    records = None
    for attempt in range(3):
        try:
            records = adapter.list_share_records(cookie)
            cookie = keep_warmed(session, account, adapter, cookie)
            break
        except RateLimited:
            if attempt >= 2:
                job.status = "failed"
                job.error = "同步失败"
                job.updated_at = now
                return
            sleeper(RETRY_DELAYS[attempt])
        except LoginRejected:
            account.status = "expired"
            account.updated_at = now
            job.status = "failed"
            job.error = EXPIRED
            job.updated_at = now
            return
        except TransferFailed:
            job.status = "failed"
            job.error = "同步失败"
            job.updated_at = now
            return
    if records is None:
        job.status = "failed"
        job.error = "同步失败"
        job.updated_at = now
        return
    apply_share_records(
        session, account, records, now, snapshot_at=_snapshot_at(job, now)
    )
    job.status = "succeeded"
    job.error = None
    job.updated_at = now


def _snapshot_at(job: Job, now: datetime) -> datetime:
    moment = _aware(now)
    created = _aware(job.created_at) if job.created_at is not None else None
    if job.directory == DAILY_CLOSE:
        ref = moment
    elif created is not None and in_previous_day_window(created):
        ref = created
    elif in_previous_day_window(moment):
        ref = moment
    else:
        return moment
    midnight = ref.astimezone(SHANGHAI).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (midnight - timedelta(seconds=1)).astimezone(timezone.utc)


def apply_share_records(
    session: Session,
    account: PanAccount,
    records: list[dict],
    now: datetime,
    snapshot_at: datetime | None = None,
) -> None:
    existing = session.scalars(
        select(ShareLink).where(ShareLink.account_id == account.id)
    ).all()
    by_key: dict[str, ShareLink] = {}
    for row in existing:
        if row.baidu_share_id:
            by_key[row.baidu_share_id] = row
        by_key[row.url.split("?", 1)[0]] = row
    seen: set[int] = set()
    for record in records:
        parsed = _record(record, now)
        if parsed is None:
            continue
        row = None
        for key in parsed["keys"]:
            row = by_key.get(key)
            if row is not None:
                break
        if row is None:
            row = ShareLink(
                user_id=account.user_id,
                account_id=account.id,
                name=parsed["name"],
                path=parsed["path"],
                url=parsed["url"],
                password=None,
                status="active",
                created_at=parsed["created_at"],
            )
            session.add(row)
        row.baidu_share_id = parsed["share_id"]
        row.name = parsed["name"]
        row.path = parsed["path"]
        if parsed["url"]:
            row.url = parsed["url"]
        row.expired = parsed["expired"]
        row.status = "active"
        row.view_count = parsed["views"]
        row.transfer_count = parsed["transfers"]
        row.download_count = parsed["downloads"]
        row.created_at = parsed["created_at"]
        session.flush()
        by_key[parsed["share_id"]] = row
        if parsed["url"]:
            by_key[parsed["url"]] = row
        seen.add(row.id)
    for row in existing:
        if row.id not in seen and row.status != "removed":
            row.status = "removed"
    session.flush()
    active = session.scalars(
        select(ShareLink).where(
            ShareLink.account_id == account.id, ShareLink.status == "active"
        )
    ).all()
    moment = snapshot_at or now
    _write_daily_snapshots(session, account, active, moment)
    _upsert_account_stat_day(session, account, active, moment)


def _upsert_account_stat_day(
    session: Session, account: PanAccount, active: list[ShareLink], now: datetime
) -> None:
    moment = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    stat_date = moment.astimezone(SHANGHAI).date()

    def _sum(field: str) -> int | None:
        values = [
            getattr(row, field) for row in active if getattr(row, field) is not None
        ]
        return sum(values) if values else None

    row = session.scalars(
        select(AccountStatDay).where(
            AccountStatDay.account_id == account.id,
            AccountStatDay.stat_date == stat_date,
        )
    ).first()
    if row is None:
        row = AccountStatDay(account_id=account.id, stat_date=stat_date)
        session.add(row)
    row.transfer_total = _sum("transfer_count")
    row.view_total = _sum("view_count")
    row.download_total = _sum("download_count")
    row.link_total = len(active)
    row.updated_at = moment


def _write_daily_snapshots(
    session: Session, account: PanAccount, active: list[ShareLink], now: datetime
) -> None:
    moment = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    local = moment.astimezone(SHANGHAI).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    day_start = local.astimezone(timezone.utc)
    day_end = (local + timedelta(days=1)).astimezone(timezone.utc)
    today = session.scalars(
        select(ShareStatSnapshot).where(
            ShareStatSnapshot.account_id == account.id,
            ShareStatSnapshot.taken_at >= day_start,
            ShareStatSnapshot.taken_at < day_end,
        )
    ).all()
    grouped: dict[int, list[ShareStatSnapshot]] = {}
    for shot in today:
        grouped.setdefault(shot.share_link_id, []).append(shot)
    for row in active:
        shots = sorted(grouped.get(row.id, []), key=lambda shot: _aware(shot.taken_at))
        if shots:
            kept = shots[-1]
            kept.view_count = row.view_count
            kept.transfer_count = row.transfer_count
            kept.download_count = row.download_count
            kept.taken_at = moment
            for extra in shots[:-1]:
                session.delete(extra)
            continue
        session.add(
            ShareStatSnapshot(
                share_link_id=row.id,
                account_id=account.id,
                view_count=row.view_count,
                transfer_count=row.transfer_count,
                download_count=row.download_count,
                taken_at=moment,
            )
        )


def query_stats(
    session: Session,
    accounts: list[PanAccount],
    now: datetime,
    rank: str,
    page: int,
    start: datetime | None = None,
    end: datetime | None = None,
    page_size: int = PAGE_SIZE,
    name: str | None = None,
) -> dict:
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    names = {account.id: account.nickname for account in accounts}
    account_ids = list(names)
    size = page_size if page_size in PAGE_SIZES else PAGE_SIZE
    offset = max(page - 1, 0) * size
    name_q = name.strip() if name and name.strip() else None
    mode = "range" if start is not None and end is not None else "history"
    if mode == "history":
        return _query_history_stats(
            session, accounts, names, account_ids, page, size, offset, current, name_q
        )
    return _query_range_stats(
        session,
        accounts,
        names,
        account_ids,
        page,
        size,
        offset,
        current,
        start,
        end,
        name_q,
    )


def _query_history_stats(
    session: Session,
    accounts: list[PanAccount],
    names: dict[int, str],
    account_ids: list[int],
    page: int,
    size: int,
    offset: int,
    current: datetime,
    name_q: str | None = None,
) -> dict:
    if not account_ids:
        return _empty_stats("history", page, size, None, None)
    filters = (ShareLink.account_id.in_(account_ids), ShareLink.status == "active")
    total = session.scalar(select(func.count()).where(*filters)) or 0
    transfers = session.scalar(
        select(func.sum(ShareLink.transfer_count)).where(*filters)
    )
    views = session.scalar(select(func.sum(ShareLink.view_count)).where(*filters))
    downloads = session.scalar(
        select(func.sum(ShareLink.download_count)).where(*filters)
    )
    table_filters = (
        (*filters, ShareLink.name.ilike(f"%{name_q}%")) if name_q else filters
    )
    rank_total = session.scalar(select(func.count()).where(*table_filters)) or 0
    rows = session.scalars(
        select(ShareLink)
        .where(*table_filters)
        .order_by(
            ShareLink.transfer_count.desc().nulls_last(), ShareLink.created_at.desc()
        )
        .offset(offset)
        .limit(size)
    ).all()
    first = session.scalar(
        select(func.min(ShareStatSnapshot.taken_at)).where(
            ShareStatSnapshot.account_id.in_(account_ids)
        )
    )
    return {
        "total": total,
        "first_snapshot_at": first,
        "range_start": None,
        "range_end": None,
        "summary": {
            "new_shares": total,
            "views": {"value": int(views) if views is not None else None, "from": None},
            "transfers": {
                "value": int(transfers) if transfers is not None else None,
                "from": None,
            },
            "downloads": {
                "value": int(downloads) if downloads is not None else None,
                "from": None,
            },
        },
        "rank": "history",
        "page": page,
        "page_size": size,
        "rank_total": rank_total,
        "rows": [
            {
                "name": row.name,
                "account_name": names.get(row.account_id, ""),
                "url": with_share_password(row.url, row.password),
                "created_at": row.created_at,
                "views": row.view_count,
                "transfers": row.transfer_count,
                "transfer_delta": None,
                "downloads": row.download_count,
                "from": None,
            }
            for row in rows
        ],
        "series": {"dates": [], "lines": []},
    }


def _query_range_stats(
    session: Session,
    accounts: list[PanAccount],
    names: dict[int, str],
    account_ids: list[int],
    page: int,
    size: int,
    offset: int,
    current: datetime,
    start: datetime,
    end: datetime,
    name_q: str | None = None,
) -> dict:
    if not account_ids:
        return _empty_stats("range", page, size, start, end)
    start_day = _aware(start).astimezone(SHANGHAI).date()
    end_day = _aware(end).astimezone(SHANGHAI).date()
    # 总链接：不含开始日当天新建，只计 (start_day, end] 内创建的链接
    after_start = datetime(
        start_day.year, start_day.month, start_day.day, tzinfo=SHANGHAI
    ) + timedelta(days=1)
    link_from = after_start.astimezone(timezone.utc)
    new_shares = (
        session.scalar(
            select(func.count()).where(
                ShareLink.account_id.in_(account_ids),
                ShareLink.status == "active",
                ShareLink.created_at >= link_from,
                ShareLink.created_at <= end,
            )
        )
        or 0
    )
    summary = {
        "new_shares": new_shares,
        "views": _day_metric_delta(
            session, account_ids, start_day, end_day, "view_total"
        ),
        "transfers": _day_metric_delta(
            session, account_ids, start_day, end_day, "transfer_total"
        ),
        "downloads": _day_metric_delta(
            session, account_ids, start_day, end_day, "download_total"
        ),
    }
    series = _day_transfer_series(session, accounts, start_day, end_day)
    rank_total, rows = _range_rank_page(
        session, names, account_ids, start_day, end_day, end, offset, size, name_q
    )
    first = session.scalar(
        select(func.min(ShareStatSnapshot.taken_at)).where(
            ShareStatSnapshot.account_id.in_(account_ids)
        )
    )
    return {
        "total": new_shares,
        "first_snapshot_at": first,
        "range_start": start,
        "range_end": end,
        "summary": summary,
        "rank": "range",
        "page": page,
        "page_size": size,
        "rank_total": rank_total,
        "rows": rows,
        "series": series,
    }


def _empty_stats(rank: str, page: int, size: int, start, end) -> dict:
    return {
        "total": 0,
        "first_snapshot_at": None,
        "range_start": start,
        "range_end": end,
        "summary": {
            "new_shares": 0,
            "views": {"value": None, "from": None},
            "transfers": {"value": None, "from": None},
            "downloads": {"value": None, "from": None},
        },
        "rank": rank,
        "page": page,
        "page_size": size,
        "rank_total": 0,
        "rows": [],
        "series": {"dates": [], "lines": []},
    }


def _day_metric_delta(
    session: Session, account_ids: list[int], start_day, end_day, field: str
) -> dict:
    """Sum end−start per account that has both day rows; skip accounts missing a day."""
    if not account_ids:
        return {"value": None, "from": None}
    start_rows = session.scalars(
        select(AccountStatDay).where(
            AccountStatDay.account_id.in_(account_ids),
            AccountStatDay.stat_date == start_day,
        )
    ).all()
    end_rows = session.scalars(
        select(AccountStatDay).where(
            AccountStatDay.account_id.in_(account_ids),
            AccountStatDay.stat_date == end_day,
        )
    ).all()
    start_by = {row.account_id: row for row in start_rows}
    end_by = {row.account_id: row for row in end_rows}
    total = 0
    seen = False
    for account_id in account_ids:
        early = start_by.get(account_id)
        late = end_by.get(account_id)
        if early is None or late is None:
            continue
        left = getattr(early, field)
        right = getattr(late, field)
        if left is None and right is None:
            continue
        total += (right or 0) - (left or 0)
        seen = True
    if not seen:
        return {"value": None, "from": None}
    return {"value": total, "from": None}


def _day_transfer_series(
    session: Session, accounts: list[PanAccount], start_day, end_day
) -> dict:
    account_ids = [account.id for account in accounts]
    days = []
    cursor = start_day
    while cursor <= end_day:
        days.append(cursor)
        cursor += timedelta(days=1)
    rows = session.scalars(
        select(AccountStatDay).where(
            AccountStatDay.account_id.in_(account_ids),
            AccountStatDay.stat_date >= start_day - timedelta(days=1),
            AccountStatDay.stat_date <= end_day,
        )
    ).all()
    by_day: dict = {}
    for row in rows:
        by_day.setdefault(row.stat_date, []).append(row)

    def total_on(day) -> int | None:
        items = by_day.get(day) or []
        values = [
            item.transfer_total for item in items if item.transfer_total is not None
        ]
        if not values and not items:
            return None
        if not values:
            return None
        return sum(values)

    totals = [total_on(day) for day in days]
    deltas: list[int | None] = []
    previous = total_on(start_day - timedelta(days=1))
    for value in totals:
        if value is None or previous is None:
            deltas.append(None)
        else:
            deltas.append(value - previous)
        if value is not None:
            previous = value
    label = "合计" if len(accounts) != 1 else (accounts[0].nickname or "未命名账号")
    account_id = accounts[0].id if len(accounts) == 1 else 0
    return {
        "dates": [day.isoformat() for day in days],
        "lines": [
            {
                "account_id": account_id,
                "account_name": label,
                "values": deltas,
                "kind": "delta",
            },
            {
                "account_id": account_id,
                "account_name": label,
                "values": totals,
                "kind": "total",
            },
        ],
    }


def _day_field_subquery(
    account_ids: list[int], day, field: str, upper: datetime | None = None
):
    """Last non-null field snapshot whose taken_at falls on the Shanghai calendar day."""
    column = getattr(ShareStatSnapshot, field)
    local_start = datetime(day.year, day.month, day.day, tzinfo=SHANGHAI)
    day_start = local_start.astimezone(timezone.utc)
    day_end = (local_start + timedelta(days=1)).astimezone(timezone.utc)
    filters = [
        ShareStatSnapshot.account_id.in_(account_ids),
        ShareStatSnapshot.taken_at >= day_start,
        ShareStatSnapshot.taken_at < day_end,
        column.is_not(None),
    ]
    if upper is not None:
        filters.append(ShareStatSnapshot.taken_at <= _aware(upper))
    ranked = (
        select(
            ShareStatSnapshot.share_link_id.label("share_link_id"),
            column.label("value"),
            func.row_number()
            .over(
                partition_by=ShareStatSnapshot.share_link_id,
                order_by=(
                    ShareStatSnapshot.taken_at.desc(),
                    ShareStatSnapshot.id.desc(),
                ),
            )
            .label("rn"),
        )
        .where(*filters)
        .subquery()
    )
    return (
        select(ranked.c.share_link_id, ranked.c.value)
        .where(ranked.c.rn == 1)
        .subquery()
    )


def _range_rank_page(
    session: Session,
    names: dict[int, str],
    account_ids: list[int],
    start_day,
    end_day,
    end: datetime,
    offset: int,
    size: int,
    name_q: str | None = None,
) -> tuple[int, list[dict]]:
    filters = (ShareLink.account_id.in_(account_ids), ShareLink.status == "active")
    if name_q:
        filters = (*filters, ShareLink.name.ilike(f"%{name_q}%"))
    rank_total = session.scalar(select(func.count()).where(*filters)) or 0
    # 周期内新建：与总链接一致，不含开始日当天，只计 (start_day, end]
    after_start = datetime(
        start_day.year, start_day.month, start_day.day, tzinfo=SHANGHAI
    ) + timedelta(days=1)
    link_from = after_start.astimezone(timezone.utc)
    end_at = _aware(end)
    before_t = _day_field_subquery(account_ids, start_day, "transfer_count")
    after_t = _day_field_subquery(account_ids, end_day, "transfer_count", upper=end)
    after_v = _day_field_subquery(account_ids, end_day, "view_count", upper=end)
    after_d = _day_field_subquery(account_ids, end_day, "download_count", upper=end)
    # 无开始日快照时，周期内新建链接的增量按结束日水位计（基线为 0）
    transfer_delta = case(
        (before_t.c.value.is_not(None), after_t.c.value - before_t.c.value),
        (
            ShareLink.created_at >= link_from,
            after_t.c.value,
        ),
        else_=None,
    )
    stmt = (
        select(
            ShareLink,
            before_t.c.value.label("t0"),
            after_t.c.value.label("t1"),
            after_v.c.value.label("v1"),
            after_d.c.value.label("d1"),
        )
        .outerjoin(before_t, before_t.c.share_link_id == ShareLink.id)
        .outerjoin(after_t, after_t.c.share_link_id == ShareLink.id)
        .outerjoin(after_v, after_v.c.share_link_id == ShareLink.id)
        .outerjoin(after_d, after_d.c.share_link_id == ShareLink.id)
        .where(*filters)
        .order_by(
            case((transfer_delta.is_(None), 1), else_=0),
            transfer_delta.desc(),
            ShareLink.created_at.desc(),
        )
        .offset(offset)
        .limit(size)
    )

    def end_value(value) -> int | None:
        return None if value is None else int(value)

    def transfer_delta_value(t0, t1, created_at) -> int | None:
        if t1 is None:
            return None
        if t0 is not None:
            return int(t1) - int(t0)
        created = _aware(created_at)
        if created >= link_from and created <= end_at:
            return int(t1)
        return None

    rows = []
    for share, t0, t1, v1, d1 in session.execute(stmt).all():
        rows.append(
            {
                "name": share.name,
                "account_name": names.get(share.account_id, ""),
                "url": with_share_password(share.url, share.password),
                "created_at": share.created_at,
                "views": end_value(v1),
                "transfers": end_value(t1),
                "transfer_delta": transfer_delta_value(t0, t1, share.created_at),
                "downloads": end_value(d1),
                "from": None,
            }
        )
    return rank_total, rows


def _record(item: dict, now: datetime) -> dict | None:
    raw = item.get("shareId")
    if isinstance(raw, str) and raw.isdecimal():
        raw = int(raw)
    if isinstance(raw, int):
        share_id = str(raw)
    elif isinstance(raw, str) and raw.strip():
        share_id = raw.strip()
    else:
        return None
    short = item.get("shorturl") if isinstance(item.get("shorturl"), str) else ""
    path = item.get("typicalPath") if isinstance(item.get("typicalPath"), str) else ""
    title = item.get("title") if isinstance(item.get("title"), str) else ""
    name = title or (path.rstrip("/").rsplit("/", 1)[-1] if path else short or share_id)
    given = item.get("url") if isinstance(item.get("url"), str) else ""
    url = given or (f"https://pan.baidu.com/s/{short}" if short else "")
    created = item.get("ctime")
    created_at = (
        datetime.fromtimestamp(created, timezone.utc)
        if isinstance(created, int)
        else now
    )
    expired_time = item.get("expiredTime")
    expired = (
        isinstance(expired_time, int)
        and expired_time > 0
        and expired_time <= int(now.timestamp())
    )
    keys = {str(share_id)}
    if short:
        keys.add(short)
        keys.add(url)
        if short.startswith("1") and len(short) > 1:
            keys.add(short[1:])
    return {
        "share_id": share_id,
        "keys": keys,
        "name": name[:255],
        "path": path[:1024],
        "url": url,
        "created_at": created_at,
        "expired": expired,
        "views": _metric(item, "views", "vCnt"),
        "transfers": _metric(item, "transfers", "tCnt"),
        "downloads": _metric(item, "downloads", "dCnt"),
    }


def _metric(item: dict, key: str, fallback: str) -> int | None:
    if key in item:
        return _count(item.get(key))
    return _count(item.get(fallback))


def _count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
