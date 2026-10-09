import secrets
import string
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_cookie, encrypt_cookie
from app.core.deps import get_current_user, get_db, now_utc
from app.crud.accounts import get_for_user
from app.crud.downloads import get as get_download
from app.crud.downloads import list_for_user as list_user_downloads
from app.crud.jobs import add as add_job
from app.crud.jobs import add_item, get_for_user as get_job_for_user, items_for, list_for_user as list_user_jobs
from app.models import DownloadTask, Job, JobItem, PanAccount, User
from app.services.links import canonical_input, parse_share_link, share_chunks
from app.services.downloads import cancel_save, start_save
from app.services.folder_download import FolderTooLarge, archive_body, archive_entries
from app.pans.baidu import BaiduAdapter
from app.pans.errors import DuplicateName, LoginRejected, NotAFile, PathNotFound, TransferFailed
from app.services.zip_stream import stored_zip_size
from app.services.quota import QuotaRejected, reserve_transfers
from app.schemas import (
    CreateFolderIn,
    DirEntryOut,
    DownloadTaskOut,
    FilePathIn,
    JobItemOut,
    JobOut,
    JobSummaryOut,
    OkOut,
    RenameIn,
    ShareIn,
    ShareOut,
    TransferIn,
)
from app.services.transfers import normalize_directory

router = APIRouter(tags=["transfers"])


def pan_client(request: Request) -> httpx.Client:
    existing = getattr(request.app.state, "pan_http_client", None)
    if existing is not None:
        return existing
    client = httpx.Client()
    request.app.state.pan_http_client = client
    return client


def owned_baidu(session: Session, user: User, account_id: int, *, allow_expired: bool = False) -> PanAccount:
    account = get_for_user(session, user.id, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    if account.provider != "baidu":
        raise HTTPException(status_code=422, detail="暂未开放")
    if account.status != "valid" and not allow_expired:
        raise HTTPException(status_code=422, detail="请重新登录百度")
    return account


def remember_cookie(session: Session, account: PanAccount, cookie: str, warmed: str) -> None:
    if warmed == cookie and account.status == "valid":
        return
    if warmed != cookie:
        account.cookie_ciphertext = encrypt_cookie(warmed, get_settings().cookie_fernet_key)
    account.status = "valid"
    account.updated_at = now_utc()
    session.commit()


def to_job(job: Job, items: list[JobItem]) -> JobOut:
    return JobOut(
        id=job.id,
        type=job.type,
        status=job.status,
        directory=job.directory,
        error=job.error,
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
    account = owned_baidu(session, user, account_id, allow_expired=True)
    try:
        directory = normalize_directory(dir)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="目标目录无效") from exc
    cookie = decrypt_cookie(account.cookie_ciphertext, get_settings().cookie_fernet_key)
    try:
        entries = BaiduAdapter(pan_client(request)).list_dir(cookie, directory)
        if account.status != "valid":
            account.status = "valid"
            account.updated_at = now_utc()
            session.commit()
    except LoginRejected as exc:
        account.status = "expired"
        account.updated_at = now_utc()
        session.commit()
        raise HTTPException(status_code=422, detail="请重新登录百度") from exc
    except PathNotFound as exc:
        raise HTTPException(status_code=422, detail="目标目录不存在") from exc
    return [
        DirEntryOut(
            name=entry.name,
            path=entry.path,
            is_dir=entry.is_dir,
            size=entry.size,
            modified_at=entry.modified_at,
            fs_id=entry.fs_id,
        )
        for entry in entries
    ]


def folder_path(directory: str, name: str) -> str:
    cleaned = name.strip()
    if not cleaned or cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        raise HTTPException(status_code=422, detail="文件夹名称无效")
    if directory == "/":
        return f"/{cleaned}"
    return f"{directory}/{cleaned}"


@router.post("/api/accounts/{account_id}/folders", response_model=DirEntryOut, status_code=201)
def create_folder(
    account_id: int,
    body: CreateFolderIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    account = owned_baidu(session, user, account_id, allow_expired=True)
    try:
        directory = normalize_directory(body.directory)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="目标目录无效") from exc
    path = folder_path(directory, body.name)
    cookie = decrypt_cookie(account.cookie_ciphertext, get_settings().cookie_fernet_key)
    adapter = BaiduAdapter(pan_client(request))
    try:
        warmed = adapter.prepare(cookie)
        remember_cookie(session, account, cookie, warmed)
        adapter.create_dir(warmed, path)
    except LoginRejected as exc:
        account.status = "expired"
        account.updated_at = now_utc()
        session.commit()
        raise HTTPException(status_code=422, detail="请重新登录百度") from exc
    except DuplicateName as exc:
        raise HTTPException(status_code=422, detail="文件夹已存在") from exc
    except PathNotFound as exc:
        raise HTTPException(status_code=422, detail="目标目录不存在") from exc
    except TransferFailed as exc:
        raise HTTPException(status_code=422, detail="新建文件夹失败") from exc
    return DirEntryOut(name=path.rsplit("/", 1)[-1], path=path, is_dir=True)


def require_child_path(path: str) -> str:
    try:
        directory = normalize_directory(path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="目标目录无效") from exc
    if directory == "/":
        raise HTTPException(status_code=422, detail="不能操作根目录")
    return directory


def clean_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned or cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        raise HTTPException(status_code=422, detail="名称无效")
    return cleaned


def open_adapter(session: Session, account: PanAccount, request: Request) -> tuple[BaiduAdapter, str]:
    cookie = decrypt_cookie(account.cookie_ciphertext, get_settings().cookie_fernet_key)
    adapter = BaiduAdapter(pan_client(request))
    try:
        warmed = adapter.prepare(cookie)
    except LoginRejected as exc:
        account.status = "expired"
        account.updated_at = now_utc()
        session.commit()
        raise HTTPException(status_code=422, detail="请重新登录百度") from exc
    remember_cookie(session, account, cookie, warmed)
    return adapter, warmed


@router.post("/api/accounts/{account_id}/files/rename", response_model=OkOut)
def rename_file(
    account_id: int,
    body: RenameIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    account = owned_baidu(session, user, account_id, allow_expired=True)
    path = require_child_path(body.path)
    name = clean_name(body.name)
    adapter, cookie = open_adapter(session, account, request)
    try:
        adapter.rename(cookie, path, name)
    except DuplicateName as exc:
        raise HTTPException(status_code=422, detail="已有同名文件") from exc
    except PathNotFound as exc:
        raise HTTPException(status_code=422, detail="文件不存在") from exc
    except LoginRejected as exc:
        account.status = "expired"
        account.updated_at = now_utc()
        session.commit()
        raise HTTPException(status_code=422, detail="请重新登录百度") from exc
    except TransferFailed as exc:
        raise HTTPException(status_code=422, detail="重命名失败") from exc
    return OkOut()


@router.post("/api/accounts/{account_id}/files/delete", response_model=OkOut)
def delete_file(
    account_id: int,
    body: FilePathIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    account = owned_baidu(session, user, account_id, allow_expired=True)
    path = require_child_path(body.path)
    adapter, cookie = open_adapter(session, account, request)
    try:
        adapter.delete(cookie, path)
    except PathNotFound as exc:
        raise HTTPException(status_code=422, detail="文件不存在") from exc
    except LoginRejected as exc:
        account.status = "expired"
        account.updated_at = now_utc()
        session.commit()
        raise HTTPException(status_code=422, detail="请重新登录百度") from exc
    except TransferFailed as exc:
        raise HTTPException(status_code=422, detail="删除失败") from exc
    return OkOut()


@router.post("/api/accounts/{account_id}/files/share", response_model=ShareOut)
def share_file(
    account_id: int,
    body: ShareIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    account = owned_baidu(session, user, account_id, allow_expired=True)
    password = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(4))
    adapter, cookie = open_adapter(session, account, request)
    try:
        url = adapter.create_share(cookie, body.fs_id, password)
    except LoginRejected as exc:
        account.status = "expired"
        account.updated_at = now_utc()
        session.commit()
        raise HTTPException(status_code=422, detail="请重新登录百度") from exc
    except TransferFailed as exc:
        raise HTTPException(status_code=422, detail="分享失败") from exc
    return ShareOut(url=url, password=password)


@router.get("/api/accounts/{account_id}/files/download")
def download_file(
    account_id: int,
    request: Request,
    path: str,
    folder: int = 0,
    name: str | None = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    account = owned_baidu(session, user, account_id, allow_expired=True)
    target = require_child_path(path)
    adapter, cookie = open_adapter(session, account, request)
    if folder:
        return folder_download(adapter, cookie, target, session, account)
    filename = safe_attachment_name(name, target.rsplit("/", 1)[-1])
    try:
        stream = adapter.open_download(cookie, target)
    except NotAFile as exc:
        raise HTTPException(status_code=422, detail="文件夹请进入后下载其中的文件") from exc
    except PathNotFound as exc:
        raise HTTPException(status_code=422, detail="文件不存在") from exc
    except LoginRejected as exc:
        account.status = "expired"
        account.updated_at = now_utc()
        session.commit()
        raise HTTPException(status_code=422, detail="请重新登录百度") from exc
    except TransferFailed as exc:
        raise HTTPException(status_code=422, detail="下载失败") from exc
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
    size = getattr(stream, "size", None)
    if isinstance(size, int):
        headers["Content-Length"] = str(size)
    return StreamingResponse(stream, media_type="application/octet-stream", headers=headers)


def safe_attachment_name(requested: str | None, fallback: str) -> str:
    cleaned = (requested or "").replace("\\", "／").replace("/", "／").replace("\x00", "").strip()
    if not cleaned or cleaned in {".", ".."} or ".." in cleaned.split("／"):
        cleaned = fallback
    return quote(cleaned[:180])


def folder_download(adapter: BaiduAdapter, cookie: str, target: str, session: Session, account: PanAccount) -> StreamingResponse:
    try:
        planned = archive_entries(adapter, cookie, target)
    except FolderTooLarge as exc:
        raise HTTPException(status_code=422, detail="目录里的文件太多，请进入下一级再下载") from exc
    except PathNotFound as exc:
        raise HTTPException(status_code=422, detail="目标目录不存在") from exc
    except LoginRejected as exc:
        account.status = "expired"
        account.updated_at = now_utc()
        session.commit()
        raise HTTPException(status_code=422, detail="请重新登录百度") from exc
    except TransferFailed as exc:
        raise HTTPException(status_code=422, detail="下载失败") from exc
    filename = quote(f"{target.rsplit('/', 1)[-1]}.zip")
    length = stored_zip_size([(name, size) for name, _path, size in planned])
    return StreamingResponse(
        archive_body(adapter, cookie, planned),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "Content-Length": str(length),
        },
    )


def to_download(task: DownloadTask) -> DownloadTaskOut:
    return DownloadTaskOut(
        id=task.id,
        account_id=task.account_id,
        name=task.name,
        path=task.path,
        status=task.status,
        phase=task.phase,
        bytes_done=task.bytes_done,
        bytes_total=task.bytes_total,
        files_done=task.files_done,
        files_total=task.files_total,
        current_name=task.current_name,
        directory=task.directory,
        error=task.error,
        created_at=task.created_at,
    )


@router.post("/api/accounts/{account_id}/files/save", response_model=DownloadTaskOut, status_code=201)
def save_directory(
    account_id: int,
    body: FilePathIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    account = owned_baidu(session, user, account_id, allow_expired=True)
    target = require_child_path(body.path)
    _adapter, cookie = open_adapter(session, account, request)
    task = start_save(
        session,
        request.app.state.session_factory,
        pan_client(request),
        cookie,
        user.id,
        account.id,
        target,
    )
    return to_download(task)


@router.get("/api/downloads", response_model=list[DownloadTaskOut])
def list_downloads(user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    rows = list_user_downloads(session, user.id)
    return [to_download(row) for row in rows]


@router.post("/api/downloads/{task_id}/cancel", response_model=DownloadTaskOut)
def cancel_download(task_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    task = get_download(session, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="下载任务不存在")
    return to_download(cancel_save(session, task))


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
    lines = share_chunks(body.links)
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
    add_job(session, job)
    session.flush()
    items: list[JobItem] = []
    for line in lines:
        parsed = parse_share_link(line)
        if parsed is None:
            status, error = "failed", "链接无法解析"
        elif parsed.provider != "baidu":
            status, error = "failed", "暂未开放"
        else:
            status, error = "pending", None
        item = JobItem(
            job_id=job.id,
            input_text=canonical_input(line),
            status=status,
            error=error,
            attempts=0,
            created_at=moment,
            updated_at=moment,
        )
        add_item(session, item)
        items.append(item)
    session.commit()
    return to_job(job, items)


@router.get("/api/jobs", response_model=list[JobSummaryOut])
def list_jobs(user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    jobs = list_user_jobs(session, user.id)
    summaries: list[JobSummaryOut] = []
    for job in jobs:
        items = items_for(session, job.id)
        summaries.append(
            JobSummaryOut(
                id=job.id,
                type=job.type,
                status=job.status,
                directory=job.directory,
                created_at=job.created_at,
                total=len(items),
                succeeded=sum(item.status == "succeeded" for item in items),
                failed=sum(item.status == "failed" for item in items),
            )
        )
    return summaries


@router.get("/api/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    job = get_job_for_user(session, user.id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    items = items_for(session, job.id)
    return to_job(job, items)
