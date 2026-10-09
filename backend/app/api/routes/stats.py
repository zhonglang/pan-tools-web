from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.routes.transfers import owned_baidu, to_job
from app.core.deps import get_current_user, get_db, now_utc
from app.crud.accounts import list_baidu
from app.crud.jobs import add as add_job
from app.crud.jobs import items_for, running_sync
from app.models import Job, User
from app.services.membership import can_use_paid_features
from app.schemas import CreatedSharesOut, JobOut, MetricOut, RankRowOut, StatsOut
from app.services.stats import PAGE_SIZES, date_bounds, query_created_shares, query_stats, range_bounds

router = APIRouter()
PAID_ONLY = "该功能仅对付费会员开放"


def _paid(user: User) -> None:
    if not can_use_paid_features(user, now_utc()):
        raise HTTPException(status_code=403, detail=PAID_ONLY)


def _page_size(value: int) -> int:
    if value not in PAGE_SIZES:
        raise HTTPException(status_code=422, detail="每页条数无效")
    return value


@router.post("/api/accounts/{account_id}/sync", response_model=JobOut, status_code=201)
def create_sync(
    account_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    del request
    _paid(user)
    account = owned_baidu(session, user, account_id)
    running = running_sync(session, account.id)
    if running is not None:
        return to_job(running, items_for(session, running.id))
    moment = now_utc()
    job = Job(
        user_id=user.id,
        account_id=account.id,
        type="sync",
        status="pending",
        directory="/",
        created_at=moment,
        updated_at=moment,
    )
    add_job(session, job)
    session.commit()
    return to_job(job, [])


@router.get("/api/accounts/{account_id}/stats", response_model=StatsOut)
def account_stats(
    account_id: int,
    span: str = Query(default="today"),
    rank: str = Query(default="history"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    _paid(user)
    account = owned_baidu(session, user, account_id, allow_expired=True)
    if span not in {"today", "week", "month"} or rank not in {"history", "range"}:
        raise HTTPException(status_code=422, detail="查询条件无效")
    moment = now_utc()
    start, end = range_bounds(span, moment)
    data = query_stats(session, [account], moment, rank, page, start, end, _page_size(page_size))
    return _stats_out(data)


@router.get("/api/stats", response_model=StatsOut)
def user_stats(
    account_id: int | None = None,
    rank: str = Query(default="range"),
    start: str | None = None,
    end: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    _paid(user)
    if rank not in {"history", "range"}:
        raise HTTPException(status_code=422, detail="查询条件无效")
    accounts = list_baidu(session, user.id)
    if account_id is not None:
        accounts = [owned_baidu(session, user, account_id, allow_expired=True)]
    moment = now_utc()
    start_at = end_at = None
    if start or end:
        if not start or not end:
            raise HTTPException(status_code=422, detail="时间范围无效")
        try:
            start_at, end_at = date_bounds(start, end, moment)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="时间范围无效") from error
    elif rank == "range":
        raise HTTPException(status_code=422, detail="时间范围无效")
    data = query_stats(session, accounts, moment, rank, page, start_at, end_at, _page_size(page_size))
    return _stats_out(data)


@router.get("/api/stats/created", response_model=CreatedSharesOut)
def created_share_stats(
    start: str,
    end: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    _paid(user)
    try:
        start_at, end_at = date_bounds(start, end, now_utc())
    except ValueError as error:
        raise HTTPException(status_code=422, detail="时间范围无效") from error
    data = query_created_shares(session, list_baidu(session, user.id), start_at, end_at, page, _page_size(page_size))
    return CreatedSharesOut(
        page=data["page"],
        page_size=data["page_size"],
        total=data["total"],
        rows=[
            RankRowOut(
                name=row["name"],
                account_name=row["account_name"],
                url=row["url"],
                created_at=row["created_at"],
                views=row["views"],
                transfers=row["transfers"],
                downloads=row["downloads"],
            )
            for row in data["rows"]
        ],
    )


def _stats_out(data: dict) -> StatsOut:
    return StatsOut(
        total=data["total"],
        first_snapshot_at=data["first_snapshot_at"],
        range_start=data["range_start"],
        range_end=data["range_end"],
        new_shares=data["summary"]["new_shares"],
        views=_metric(data["summary"]["views"]),
        transfers=_metric(data["summary"]["transfers"]),
        downloads=_metric(data["summary"]["downloads"]),
        rank=data["rank"],
        page=data["page"],
        page_size=data["page_size"],
        rank_total=data["rank_total"],
        dates=data["series"]["dates"],
        lines=data["series"]["lines"],
        rows=[
            RankRowOut(
                name=row["name"],
                account_name=row["account_name"],
                url=row["url"],
                created_at=row["created_at"],
                views=row["views"],
                transfers=row["transfers"],
                downloads=row["downloads"],
            )
            for row in data["rows"]
        ],
    )


def _metric(raw: dict) -> MetricOut:
    return MetricOut(value=raw["value"], from_time=raw["from"])
