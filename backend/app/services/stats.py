from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_cookie
from app.services.membership import can_use_paid_features
from app.models import Job, PanAccount, ShareLink, ShareStatSnapshot, User
from app.pans import adapter_for
from app.pans.errors import LoginRejected, RateLimited, TransferFailed
from app.services.transfers import EXPIRED, RETRY_DELAYS

SHANGHAI = ZoneInfo("Asia/Shanghai")
PAGE_SIZE = 10
PAGE_SIZES = (10, 20, 50)
DAILY_CLOSE = "daily-close"


def date_bounds(start_day: str, end_day: str, now: datetime) -> tuple[datetime, datetime]:
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
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    local = current.astimezone(SHANGHAI)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if span == "week":
        start -= timedelta(days=6)
    elif span == "month":
        start -= timedelta(days=29)
    elif span != "today":
        raise ValueError("时间范围无效")
    return start.astimezone(timezone.utc), current


def enqueue_daily_syncs(session: Session, now: datetime) -> None:
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    local = current.astimezone(SHANGHAI)
    if local.hour > 5 or (local.hour, local.minute) < (0, 5):
        return
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    accounts = session.scalars(
        select(PanAccount).where(PanAccount.provider.in_(("baidu", "quark")), PanAccount.status == "valid")
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
    account = session.get(PanAccount, job.account_id)
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
    apply_share_records(session, account, records, now, snapshot_at=_snapshot_at(job, now))
    job.status = "succeeded"
    job.error = None
    job.updated_at = now


def _snapshot_at(job: Job, now: datetime) -> datetime:
    if job.directory != DAILY_CLOSE:
        return now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    moment = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    midnight = moment.astimezone(SHANGHAI).replace(hour=0, minute=0, second=0, microsecond=0)
    return (midnight - timedelta(seconds=1)).astimezone(timezone.utc)


def apply_share_records(
    session: Session,
    account: PanAccount,
    records: list[dict],
    now: datetime,
    snapshot_at: datetime | None = None,
) -> None:
    existing = session.scalars(select(ShareLink).where(ShareLink.account_id == account.id)).all()
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
        select(ShareLink).where(ShareLink.account_id == account.id, ShareLink.status == "active")
    ).all()
    _write_daily_snapshots(session, account, active, snapshot_at or now)


def _write_daily_snapshots(session: Session, account: PanAccount, active: list[ShareLink], now: datetime) -> None:
    moment = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    local = moment.astimezone(SHANGHAI).replace(hour=0, minute=0, second=0, microsecond=0)
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
) -> dict:
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    names = {account.id: account.nickname for account in accounts}
    account_ids = list(names)
    shares = []
    snapshots = []
    if account_ids:
        shares = session.scalars(
            select(ShareLink).where(ShareLink.account_id.in_(account_ids), ShareLink.status == "active")
        ).all()
        snapshots = session.scalars(
            select(ShareStatSnapshot)
            .where(ShareStatSnapshot.account_id.in_(account_ids))
            .order_by(ShareStatSnapshot.taken_at)
        ).all()
    by_share: dict[int, list[ShareStatSnapshot]] = {}
    for shot in snapshots:
        by_share.setdefault(shot.share_link_id, []).append(shot)
    first = snapshots[0].taken_at if snapshots else None
    if rank == "history":
        summary = {
            "new_shares": len(shares),
            "views": _sum_cumulative(shares, "view_count"),
            "transfers": _sum_cumulative(shares, "transfer_count"),
            "downloads": _sum_cumulative(shares, "download_count"),
        }
        rows = [_rank_row(share, by_share.get(share.id, []), start or current, current, rank, names.get(share.account_id, "")) for share in shares]
    else:
        if start is None or end is None:
            raise ValueError("时间范围无效")
        bounded = _aware(end) < _aware(current)
        new_shares = sum(1 for share in shares if start <= _aware(share.created_at) <= end)
        summary = {
            "new_shares": new_shares,
            "views": _sum_metric(shares, by_share, start, end, "view_count", bounded),
            "transfers": _sum_metric(shares, by_share, start, end, "transfer_count", bounded),
            "downloads": _sum_metric(shares, by_share, start, end, "download_count", bounded),
        }
        rows = [
            _rank_row(share, by_share.get(share.id, []), start, end, rank, names.get(share.account_id, ""), bounded)
            for share in shares
        ]
    rows.sort(key=lambda row: _rank_key(row, rank))
    total = len(rows)
    size = page_size if page_size in PAGE_SIZES else PAGE_SIZE
    offset = max(page - 1, 0) * size
    window_start, window_end = (start, end) if start is not None and end is not None else range_bounds("week", current)
    return {
        "total": len(shares),
        "first_snapshot_at": first,
        "range_start": start,
        "range_end": end,
        "summary": summary,
        "rank": rank,
        "page": page,
        "page_size": size,
        "rank_total": total,
        "rows": rows[offset : offset + size],
        "series": _transfer_series(accounts, snapshots, window_start, window_end, rank),
    }


def _transfer_series(
    accounts: list[PanAccount],
    snapshots: list[ShareStatSnapshot],
    start: datetime,
    end: datetime,
    rank: str,
) -> dict:
    window_end = _aware(end).astimezone(SHANGHAI)
    first_day = _aware(start).astimezone(SHANGHAI).date()
    last_day = window_end.date()
    days = []
    cursor = first_day
    while cursor <= last_day:
        days.append(cursor)
        cursor += timedelta(days=1)

    def cutoff_for(day) -> datetime:
        if day == last_day:
            return window_end.astimezone(timezone.utc)
        return datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=SHANGHAI).astimezone(timezone.utc)

    previous_day = first_day - timedelta(days=1)
    baseline = datetime(previous_day.year, previous_day.month, previous_day.day, 23, 59, 59, tzinfo=SHANGHAI).astimezone(timezone.utc)
    by_account: dict[int, dict[int, list[ShareStatSnapshot]]] = {}
    for shot in snapshots:
        by_account.setdefault(shot.account_id, {}).setdefault(shot.share_link_id, []).append(shot)
    cutoffs = [cutoff_for(day) for day in days]
    lines = []
    for account in sorted(accounts, key=lambda item: item.id):
        shares = by_account.get(account.id, {})
        if rank == "history":
            values = [_account_level(shares, cutoff) for cutoff in cutoffs]
        else:
            values = []
            previous = baseline
            for cutoff in cutoffs:
                values.append(_account_delta(shares, previous, cutoff))
                previous = cutoff
        lines.append({"account_id": account.id, "account_name": account.nickname or "未命名账号", "values": values})
    return {"dates": [day.isoformat() for day in days], "lines": lines}


def _latest_transfer(shots: list[ShareStatSnapshot], cutoff: datetime) -> int | None:
    found = None
    limit = _aware(cutoff)
    for shot in shots:
        if _aware(shot.taken_at) > limit:
            break
        if shot.transfer_count is not None:
            found = shot.transfer_count
    return found


def _account_level(shares: dict[int, list[ShareStatSnapshot]], cutoff: datetime) -> int | None:
    total = 0
    seen = False
    for shots in shares.values():
        value = _latest_transfer(shots, cutoff)
        if value is None:
            continue
        total += value
        seen = True
    return total if seen else None


def _account_delta(shares: dict[int, list[ShareStatSnapshot]], previous: datetime, cutoff: datetime) -> int | None:
    deltas = []
    for shots in shares.values():
        current = _latest_transfer(shots, cutoff)
        before = _latest_transfer(shots, previous)
        if current is None or before is None:
            continue
        deltas.append(current - before)
    return sum(deltas) if deltas else None


def _sum_cumulative(shares, field: str) -> dict:
    values = [getattr(share, field) for share in shares if getattr(share, field) is not None]
    if not values:
        return {"value": None, "from": None}
    return {"value": sum(values), "from": None}


def _sum_metric(shares, by_share, start, end, field: str, bounded: bool) -> dict:
    values: list[int] = []
    starts: list[datetime] = []
    rule1 = False
    for share in shares:
        delta, origin, used_rule1 = _delta(by_share.get(share.id, []), start, end, getattr(share, field), field, bounded)
        if delta is None:
            continue
        values.append(delta)
        if used_rule1:
            rule1 = True
        elif origin is not None:
            starts.append(origin)
    if not values:
        return {"value": None, "from": None}
    return {"value": sum(values), "from": None if rule1 or not starts else min(starts)}


def _rank_row(
    share: ShareLink,
    shots: list[ShareStatSnapshot],
    start: datetime,
    end: datetime,
    rank: str,
    account_name: str,
    bounded: bool = False,
) -> dict:
    if rank == "history":
        views, transfers, downloads = share.view_count, share.transfer_count, share.download_count
        origin = None
    else:
        views, _, _ = _delta(shots, start, end, share.view_count, "view_count", bounded)
        transfers, origin, _ = _delta(shots, start, end, share.transfer_count, "transfer_count", bounded)
        downloads, _, _ = _delta(shots, start, end, share.download_count, "download_count", bounded)
    return {
        "name": share.name,
        "account_name": account_name,
        "url": share.url,
        "created_at": share.created_at,
        "views": views,
        "transfers": transfers,
        "downloads": downloads,
        "from": origin,
    }


def _rank_key(row: dict, rank: str):
    created = _aware(row["created_at"])
    value = row["transfers"]
    if value is None:
        return (1, -created.timestamp())
    return (0, -value, -created.timestamp())


def query_created_shares(
    session: Session,
    accounts: list[PanAccount],
    start: datetime,
    end: datetime,
    page: int,
    page_size: int,
) -> dict:
    names = {account.id: account.nickname for account in accounts}
    shares = []
    if names:
        shares = session.scalars(
            select(ShareLink).where(ShareLink.account_id.in_(list(names)), ShareLink.status == "active")
        ).all()
    matched = [share for share in shares if start <= _aware(share.created_at) <= end]
    matched.sort(
        key=lambda share: (
            share.transfer_count is None,
            -(share.transfer_count or 0),
            share.download_count is None,
            -(share.download_count or 0),
            share.view_count is None,
            -(share.view_count or 0),
            -_aware(share.created_at).timestamp(),
        )
    )
    size = page_size if page_size in PAGE_SIZES else PAGE_SIZE
    offset = max(page - 1, 0) * size
    rows = [
        {
            "name": share.name,
            "account_name": names.get(share.account_id, ""),
            "url": share.url,
            "created_at": share.created_at,
            "views": share.view_count,
            "transfers": share.transfer_count,
            "downloads": share.download_count,
        }
        for share in matched[offset : offset + size]
    ]
    return {"page": page, "page_size": size, "total": len(matched), "rows": rows}


def _delta(shots: list[ShareStatSnapshot], start: datetime, end: datetime, latest: int | None, field: str, bounded: bool):
    before = [shot for shot in shots if _aware(shot.taken_at) <= start and getattr(shot, field) is not None]
    inside = [shot for shot in shots if start < _aware(shot.taken_at) <= end and getattr(shot, field) is not None]
    if bounded:
        observed = [shot for shot in shots if _aware(shot.taken_at) <= end and getattr(shot, field) is not None]
        if before and observed:
            return getattr(observed[-1], field) - getattr(before[-1], field), None, True
        if len(inside) >= 2:
            return getattr(inside[-1], field) - getattr(inside[0], field), _aware(inside[0].taken_at), False
        return None, None, False
    if latest is None:
        return None, None, False
    if before:
        return latest - getattr(before[-1], field), None, True
    if len(inside) >= 2:
        return getattr(inside[-1], field) - getattr(inside[0], field), _aware(inside[0].taken_at), False
    return None, None, False


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
    created_at = datetime.fromtimestamp(created, timezone.utc) if isinstance(created, int) else now
    expired_time = item.get("expiredTime")
    expired = isinstance(expired_time, int) and expired_time > 0 and expired_time <= int(now.timestamp())
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
