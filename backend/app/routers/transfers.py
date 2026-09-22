import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto import decrypt_cookie
from app.deps import get_current_user, get_db, now_utc
from app.links import parse_share_link, split_link_lines
from app.models import Job, JobItem, PanAccount, User
from app.pans.baidu import BaiduAdapter
from app.pans.errors import LoginRejected, PathNotFound
from app.quota import QuotaRejected, reserve_transfers
from app.schemas import DirEntryOut, JobItemOut, JobOut, TransferIn
from app.transfers import normalize_directory

router = APIRouter(tags=["transfers"])


def pan_client(request: Request) -> httpx.Client:
    existing = getattr(request.app.state, "pan_http_client", None)
    if existing is not None:
        return existing
    client = httpx.Client()
    request.app.state.pan_http_client = client
    return client


def owned_baidu(session: Session, user: User, account_id: int) -> PanAccount:
    account = session.scalar(select(PanAccount).where(PanAccount.id == account_id, PanAccount.user_id == user.id))
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    if account.provider != "baidu":
        raise HTTPException(status_code=422, detail="暂未开放")
    if account.status != "valid":
        raise HTTPException(status_code=422, detail="请重新登录百度")
    return account


def to_job(job: Job, items: list[JobItem]) -> JobOut:
    return JobOut(
        id=job.id,
        status=job.status,
        directory=job.directory,
        items=[
            JobItemOut(
                id=item.id,
                status=item.status,
                input_text=item.input_text,
                error=item.error,
                result=item.result,
                attempts=item.attempts,
            )
            for item in items
        ],
    )


@router.get("/api/accounts/{account_id}/files", response_model=list[DirEntryOut])
def list_files(
    account_id: int,
    request: Request,
    dir: str = "/",
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    account = owned_baidu(session, user, account_id)
    try:
        directory = normalize_directory(dir)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="目标目录无效") from exc
    cookie = decrypt_cookie(account.cookie_ciphertext, get_settings().cookie_fernet_key)
    try:
        entries = BaiduAdapter(pan_client(request)).list_dir(cookie, directory)
    except LoginRejected as exc:
        account.status = "expired"
        account.updated_at = now_utc()
        session.commit()
        raise HTTPException(status_code=422, detail="请重新登录百度") from exc
    except PathNotFound as exc:
        raise HTTPException(status_code=422, detail="目标目录不存在") from exc
    return [DirEntryOut(name=entry.name, path=entry.path, is_dir=entry.is_dir) for entry in entries]


@router.post("/api/transfers", response_model=JobOut, status_code=201)
def create_transfer(
    body: TransferIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    account = owned_baidu(session, user, body.account_id)
    try:
        directory = normalize_directory(body.directory)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    lines = split_link_lines(body.links)
    if not lines:
        raise HTTPException(status_code=422, detail="请粘贴分享链接")
    moment = body.now or now_utc()
    if directory != "/":
        cookie = decrypt_cookie(account.cookie_ciphertext, get_settings().cookie_fernet_key)
        try:
            BaiduAdapter(pan_client(request)).list_dir(cookie, directory)
        except LoginRejected as exc:
            account.status = "expired"
            account.updated_at = moment
            session.commit()
            raise HTTPException(status_code=422, detail="请重新登录百度") from exc
        except PathNotFound as exc:
            raise HTTPException(status_code=422, detail="目标目录不存在") from exc
    try:
        reserve_transfers(session, user, moment, len(lines))
    except QuotaRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    job = Job(
        user_id=user.id,
        account_id=account.id,
        type="transfer",
        status="pending",
        directory=directory,
        created_at=moment,
        updated_at=moment,
    )
    session.add(job)
    session.flush()
    items: list[JobItem] = []
    for line in lines:
        parsed = parse_share_link(line)
        item = JobItem(
            job_id=job.id,
            input_text=line,
            status="failed" if parsed is None else "pending",
            error="链接无法解析" if parsed is None else None,
            attempts=0,
            created_at=moment,
            updated_at=moment,
        )
        session.add(item)
        items.append(item)
    session.commit()
    return to_job(job, items)


@router.get("/api/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    job = session.scalar(select(Job).where(Job.id == job_id, Job.user_id == user.id))
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    items = session.scalars(select(JobItem).where(JobItem.job_id == job.id).order_by(JobItem.id)).all()
    return to_job(job, items)
