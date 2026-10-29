import secrets
import string
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_cookie, encrypt_cookie
from app.core.deps import get_current_user, get_db, now_utc
from app.crud.accounts import get_for_user
from app.crud.downloads import get as get_download
from app.crud.downloads import list_for_user as list_user_downloads
from app.crud.jobs import add as add_job
from app.crud.jobs import (
    add_item,
    get_for_user as get_job_for_user,
    items_for,
    summaries_for_user,
)
from app.crud.uploads import get as get_upload
from app.crud.uploads import list_for_user as list_user_uploads
from app.models import DownloadTask, Job, JobItem, PanAccount, UploadTask, User
from app.services.links import canonical_input, parse_share_link, share_chunks
from app.services.downloads import cancel_save, start_save
from app.services.folder_download import FolderTooLarge, archive_body, archive_entries
from app.services.uploads import cancel_upload, start_upload, upload_max_bytes
from app.pans import adapter_for
from app.pans.baidu import BaiduAdapter
from app.pans.errors import (
    DuplicateName,
    LoginRejected,
    NotAFile,
    PathNotFound,
    TransferFailed,
)
from app.services.zip_stream import stored_zip_size
from app.services.quota import QuotaRejected, reserve_transfers
from app.schemas import (
    CopyIn,
    CopyOut,
    CopyTargetResultOut,
    CreateFolderIn,
    DirEntryOut,
    DownloadTaskOut,
    FilePathIn,
    FilePathsIn,
    JobItemOut,
    JobOut,
    JobSummaryOut,
    OkOut,
    RenameIn,
    ShareIn,
    ShareOut,
    TransferIn,
    UploadTaskOut,
)
from app.schemas.linked_rename import LinkedRenameIn, LinkedRenameOut
from app.services.copying import MAX_RENAME_ATTEMPTS, next_copy_name, validate_targets
from app.services.linked_rename import linked_rename, list_members, primary_member
from app.services.transfers import clean_directory_label, normalize_directory

router = APIRouter(tags=["transfers"])


def pan_client(request: Request) -> httpx.Client:
    existing = getattr(request.app.state, "pan_http_client", None)
    if existing is not None:
        return existing
    client = httpx.Client()
    request.app.state.pan_http_client = client
    return client


def relogin(provider: str) -> str:
    name = {"quark": "夸克", "xunlei": "迅雷"}.get(provider, "百度")
    return f"请重新登录{name}"


def owned_baidu(
    session: Session, user: User, account_id: int, *, allow_expired: bool = False
) -> PanAccount:
    account = get_for_user(session, user.id, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    if account.provider != "baidu":
        raise HTTPException(status_code=422, detail="暂未开放")
    if account.status != "valid" and not allow_expired:
        raise HTTPException(status_code=422, detail="请重新登录百度")
    return account


def owned_drive(
    session: Session, user: User, account_id: int, *, allow_expired: bool = False
) -> PanAccount:
    account = get_for_user(session, user.id, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    if account.provider not in {"baidu", "quark", "xunlei"}:
        raise HTTPException(status_code=422, detail="暂未开放")
    if account.status != "valid" and not allow_expired:
        raise HTTPException(status_code=422, detail=relogin(account.provider))
    return account


def remember_cookie(
    session: Session, account: PanAccount, cookie: str, warmed: str
) -> None:
    if warmed == cookie and account.status == "valid":
        return
    if warmed != cookie:
        account.cookie_ciphertext = encrypt_cookie(
            warmed, get_settings().cookie_fernet_key
        )
    account.status = "valid"
    account.updated_at = now_utc()
    session.commit()


def persist_warmed(session: Session, account: PanAccount, cookie: str, adapter) -> None:
    warmed = getattr(adapter, "warmed", None)
    if isinstance(warmed, str):
        remember_cookie(session, account, cookie, warmed)


def to_job(job: Job, items: list[JobItem]) -> JobOut:
    return JobOut(
        id=job.id,
        type=job.type,
        status=job.status,
        directory=job.directory,
        directory_label=job.directory_label,
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
    account = owned_drive(session, user, account_id, allow_expired=True)
    try:
        directory = normalize_directory(dir)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="目标目录无效") from exc
    cookie = decrypt_cookie(account.cookie_ciphertext, get_settings().cookie_fernet_key)
    adapter = adapter_for(account.provider, pan_client(request))
    try:
        entries = adapter.list_dir(cookie, directory)
        persist_warmed(session, account, cookie, adapter)
        if account.status != "valid":
            account.status = "valid"
            account.updated_at = now_utc()
            session.commit()
    except LoginRejected as exc:
        account.status = "expired"
        account.updated_at = now_utc()
        session.commit()
        raise HTTPException(status_code=422, detail=relogin(account.provider)) from exc
    except PathNotFound as exc:
        raise HTTPException(status_code=422, detail="目标目录不存在") from exc
    return [
        DirEntryOut(
            name=entry.name,
            path=entry.path,
            is_dir=entry.is_dir,
            size=entry.size,
            created_at=entry.created_at,
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


@router.post(
    "/api/accounts/{account_id}/folders", response_model=DirEntryOut, status_code=201
)
def create_folder(
    account_id: int,
    body: CreateFolderIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    account = owned_drive(session, user, account_id, allow_expired=True)
    try:
        directory = normalize_directory(body.directory)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="目标目录无效") from exc
    path = folder_path(directory, body.name)
    cookie = decrypt_cookie(account.cookie_ciphertext, get_settings().cookie_fernet_key)
    adapter = adapter_for(account.provider, pan_client(request))
    try:
        if account.provider in {"quark", "xunlei"}:
            created = adapter.create_dir(cookie, directory, path.rsplit("/", 1)[-1])
            warmed = getattr(adapter, "warmed", None)
            if isinstance(warmed, str):
                remember_cookie(session, account, cookie, warmed)
            return DirEntryOut(name=created.name, path=created.path, is_dir=True)
        warmed = adapter.prepare(cookie)
        remember_cookie(session, account, cookie, warmed)
        adapter.create_dir(warmed, path)
    except LoginRejected as exc:
        account.status = "expired"
        account.updated_at = now_utc()
        session.commit()
        raise HTTPException(status_code=422, detail=relogin(account.provider)) from exc
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


def open_adapter(session: Session, account: PanAccount, request: Request):
    cookie = decrypt_cookie(account.cookie_ciphertext, get_settings().cookie_fernet_key)
    adapter = adapter_for(account.provider, pan_client(request))
    if account.provider == "quark":
        return adapter, cookie
    try:
        warmed = adapter.prepare(cookie)
    except LoginRejected as exc:
        account.status = "expired"
        account.updated_at = now_utc()
        session.commit()
        raise HTTPException(status_code=422, detail=relogin(account.provider)) from exc
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
    account = owned_drive(session, user, account_id, allow_expired=True)
    path = require_child_path(body.path)
    name = clean_name(body.name)
    adapter, cookie = open_adapter(session, account, request)
    try:
        adapter.rename(cookie, path, name)
        persist_warmed(session, account, cookie, adapter)
    except DuplicateName as exc:
        raise HTTPException(status_code=422, detail="已有同名文件") from exc
    except PathNotFound as exc:
        raise HTTPException(status_code=422, detail="文件不存在") from exc
    except LoginRejected as exc:
        account.status = "expired"
        account.updated_at = now_utc()
        session.commit()
        raise HTTPException(status_code=422, detail=relogin(account.provider)) from exc
    except TransferFailed as exc:
        raise HTTPException(status_code=422, detail="重命名失败") from exc
    return OkOut()


@router.post("/api/files/linked-rename", response_model=LinkedRenameOut)
def linked_rename_file(
    body: LinkedRenameIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    path = require_child_path(body.path)
    new_name = clean_name(body.name)
    current_name = clean_name(body.current_name)
    members = list_members(session, user.id)
    primary = primary_member(members)
    if primary is None:
        raise HTTPException(
            status_code=422, detail="请先在系统配置中设置关联重命名主目录"
        )
    if body.account_id != primary.account_id:
        raise HTTPException(status_code=422, detail="只能从主网盘目录发起关联重命名")

    adapters: dict[int, tuple] = {}
    session_lock = threading.Lock()

    def ensure(account_id: int):
        cached = adapters.get(account_id)
        if cached is not None:
            return cached
        with session_lock:
            cached = adapters.get(account_id)
            if cached is not None:
                return cached
            account = owned_drive(session, user, account_id, allow_expired=True)
            pair = open_adapter(session, account, request)
            adapters[account_id] = (account, pair[0], pair[1])
            return adapters[account_id]

    def list_folders(account_id: int, directory: str) -> list[tuple[str, str]]:
        account, adapter, cookie = ensure(account_id)
        try:
            entries = adapter.list_dir(cookie, directory)
            with session_lock:
                persist_warmed(session, account, cookie, adapter)
        except LoginRejected as exc:
            with session_lock:
                account.status = "expired"
                account.updated_at = now_utc()
                session.commit()
            raise RuntimeError(relogin(account.provider)) from exc
        except PathNotFound as exc:
            raise RuntimeError("目录不存在") from exc
        return [(entry.path, entry.name) for entry in entries if entry.is_dir]

    def rename(account_id: int, file_path: str, name: str) -> None:
        account, adapter, cookie = ensure(account_id)
        try:
            adapter.rename(cookie, file_path, name)
            with session_lock:
                persist_warmed(session, account, cookie, adapter)
        except DuplicateName as exc:
            raise RuntimeError("已有同名文件") from exc
        except PathNotFound as exc:
            raise RuntimeError("文件不存在") from exc
        except LoginRejected as exc:
            with session_lock:
                account.status = "expired"
                account.updated_at = now_utc()
                session.commit()
            raise RuntimeError(relogin(account.provider)) from exc
        except TransferFailed as exc:
            raise RuntimeError("重命名失败") from exc

    # Warm adapters on the request thread before peer work fans out.
    for member in members:
        ensure(member.account_id)

    # Ensure source is under primary directory listing
    try:
        primary_folders = list_folders(primary.account_id, primary.directory)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if path not in {item[0] for item in primary_folders}:
        raise HTTPException(
            status_code=422, detail="请在主目录下选择要关联重命名的文件夹"
        )

    try:
        result = linked_rename(
            session,
            user.id,
            account_id=body.account_id,
            path=path,
            current_name=current_name,
            new_name=new_name,
            list_folders=list_folders,
            rename=rename,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    return LinkedRenameOut(
        renamed=result.renamed,
        skipped=result.skipped,
        failed=result.failed,
        errors=result.errors,
    )


@router.post("/api/accounts/{account_id}/files/delete", response_model=OkOut)
def delete_file(
    account_id: int,
    body: FilePathIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    account = owned_drive(session, user, account_id, allow_expired=True)
    path = require_child_path(body.path)
    adapter, cookie = open_adapter(session, account, request)
    try:
        adapter.delete(cookie, path)
        persist_warmed(session, account, cookie, adapter)
    except PathNotFound as exc:
        raise HTTPException(status_code=422, detail="文件不存在") from exc
    except LoginRejected as exc:
        account.status = "expired"
        account.updated_at = now_utc()
        session.commit()
        raise HTTPException(status_code=422, detail=relogin(account.provider)) from exc
    except TransferFailed as exc:
        raise HTTPException(status_code=422, detail="删除失败") from exc
    return OkOut()


@router.post("/api/accounts/{account_id}/files/delete-batch", response_model=OkOut)
def delete_files(
    account_id: int,
    body: FilePathsIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    account = owned_drive(session, user, account_id, allow_expired=True)
    paths = [require_child_path(path) for path in body.paths]
    adapter, cookie = open_adapter(session, account, request)
    try:
        adapter.delete_many(cookie, paths)
        persist_warmed(session, account, cookie, adapter)
    except PathNotFound as exc:
        raise HTTPException(status_code=422, detail="文件不存在") from exc
    except LoginRejected as exc:
        account.status = "expired"
        account.updated_at = now_utc()
        session.commit()
        raise HTTPException(status_code=422, detail=relogin(account.provider)) from exc
    except TransferFailed as exc:
        raise HTTPException(status_code=422, detail="删除失败") from exc
    return OkOut()


@router.post("/api/accounts/{account_id}/files/copy", response_model=CopyOut)
def copy_files(
    account_id: int,
    body: CopyIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    account = owned_drive(session, user, account_id, allow_expired=True)
    source = require_child_path(body.path)
    name = clean_name(body.name)
    try:
        targets = validate_targets(source, body.targets)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    adapter, cookie = open_adapter(session, account, request)
    results: list[CopyTargetResultOut] = []
    expired = False
    for dest in targets:
        if expired:
            results.append(
                CopyTargetResultOut(
                    path=dest, name=name, ok=False, error=relogin(account.provider)
                )
            )
            continue
        placed = None
        error = None
        for attempt in range(MAX_RENAME_ATTEMPTS):
            candidate = next_copy_name(name, is_dir=body.is_dir, attempt=attempt)
            try:
                adapter.copy(cookie, source, dest, candidate)
                placed = candidate
                break
            except DuplicateName:
                continue
            except LoginRejected:
                expired = True
                account.status = "expired"
                account.updated_at = now_utc()
                session.commit()
                error = relogin(account.provider)
                break
            except PathNotFound:
                error = "目录不存在"
                break
            except TransferFailed:
                error = "复制失败"
                break
        if placed is None and error is None:
            error = "已有同名文件"
        results.append(
            CopyTargetResultOut(
                path=dest, name=placed or name, ok=placed is not None, error=error
            )
        )
    persist_warmed(session, account, cookie, adapter)
    return CopyOut(
        succeeded=sum(1 for row in results if row.ok),
        failed=sum(1 for row in results if not row.ok),
        results=results,
    )


@router.post("/api/accounts/{account_id}/files/share", response_model=ShareOut)
def share_file(
    account_id: int,
    body: ShareIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    account = owned_drive(session, user, account_id, allow_expired=True)
    password = (
        ""
        if account.provider == "quark"
        else "".join(
            secrets.choice(string.ascii_letters + string.digits) for _ in range(4)
        )
    )
    adapter, cookie = open_adapter(session, account, request)
    try:
        created = adapter.create_share(
            cookie, body.fs_id, password, path=body.path, name=body.name
        )
        if isinstance(created, tuple):
            url, password = created
        else:
            url = created
        persist_warmed(session, account, cookie, adapter)
    except LoginRejected as exc:
        account.status = "expired"
        account.updated_at = now_utc()
        session.commit()
        raise HTTPException(status_code=422, detail=relogin(account.provider)) from exc
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
    account = owned_drive(session, user, account_id, allow_expired=True)
    target = require_child_path(path)
    adapter, cookie = open_adapter(session, account, request)
    if folder:
        return folder_download(adapter, cookie, target, session, account)
    filename = safe_attachment_name(name, target.rsplit("/", 1)[-1])
    try:
        stream = adapter.open_download(cookie, target)
        persist_warmed(session, account, cookie, adapter)
    except NotAFile as exc:
        raise HTTPException(
            status_code=422, detail="文件夹请进入后下载其中的文件"
        ) from exc
    except PathNotFound as exc:
        raise HTTPException(status_code=422, detail="文件不存在") from exc
    except LoginRejected as exc:
        account.status = "expired"
        account.updated_at = now_utc()
        session.commit()
        raise HTTPException(status_code=422, detail=relogin(account.provider)) from exc
    except TransferFailed as exc:
        detail = str(exc).strip() if str(exc).strip() else "下载失败"
        raise HTTPException(status_code=422, detail=detail) from exc
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
    size = getattr(stream, "size", None)
    if isinstance(size, int):
        headers["Content-Length"] = str(size)
    return StreamingResponse(
        stream, media_type="application/octet-stream", headers=headers
    )


def safe_attachment_name(requested: str | None, fallback: str) -> str:
    cleaned = (
        (requested or "")
        .replace("\\", "／")
        .replace("/", "／")
        .replace("\x00", "")
        .strip()
    )
    if not cleaned or cleaned in {".", ".."} or ".." in cleaned.split("／"):
        cleaned = fallback
    return quote(cleaned[:180])


def folder_download(
    adapter: BaiduAdapter,
    cookie: str,
    target: str,
    session: Session,
    account: PanAccount,
) -> StreamingResponse:
    try:
        planned = archive_entries(adapter, cookie, target)
        persist_warmed(session, account, cookie, adapter)
    except FolderTooLarge as exc:
        raise HTTPException(
            status_code=422, detail="目录里的文件太多，请进入下一级再下载"
        ) from exc
    except PathNotFound as exc:
        raise HTTPException(status_code=422, detail="目标目录不存在") from exc
    except LoginRejected as exc:
        account.status = "expired"
        account.updated_at = now_utc()
        session.commit()
        raise HTTPException(status_code=422, detail=relogin(account.provider)) from exc
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


@router.post(
    "/api/accounts/{account_id}/files/save",
    response_model=DownloadTaskOut,
    status_code=201,
)
def save_directory(
    account_id: int,
    body: FilePathIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    account = owned_drive(session, user, account_id, allow_expired=True)
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
def list_downloads(
    user: User = Depends(get_current_user), session: Session = Depends(get_db)
):
    rows = list_user_downloads(session, user.id)
    return [to_download(row) for row in rows]


@router.post("/api/downloads/{task_id}/cancel", response_model=DownloadTaskOut)
def cancel_download(
    task_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    task = get_download(session, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="下载任务不存在")
    return to_download(cancel_save(session, task))


def to_upload(task: UploadTask) -> UploadTaskOut:
    return UploadTaskOut.model_validate(task)


@router.post(
    "/api/accounts/{account_id}/files/upload",
    response_model=UploadTaskOut,
    status_code=201,
)
async def upload_files(
    account_id: int,
    request: Request,
    dest: str = Form(...),
    files: list[UploadFile] = File(...),
    relative_paths: list[str] | None = Form(None),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    account = owned_drive(session, user, account_id, allow_expired=True)
    try:
        dest_path = normalize_directory(dest)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="目标目录无效") from exc
    if not files:
        raise HTTPException(status_code=422, detail="请选择文件")
    paths = relative_paths or []
    if paths and len(paths) != len(files):
        raise HTTPException(status_code=422, detail="相对路径数量不匹配")
    temp_root = Path(tempfile.mkdtemp(prefix="pan-upload-"))
    items: list[tuple[str, Path, int]] = []
    total = 0
    try:
        for index, upload in enumerate(files):
            relative = (
                (paths[index] if index < len(paths) else None)
                or upload.filename
                or f"file-{index}"
            )
            relative = relative.replace("\\", "/").lstrip("/")
            if not relative or ".." in relative.split("/"):
                raise HTTPException(status_code=422, detail="文件路径无效")
            local = temp_root / f"{index}-{Path(relative).name}"
            size = 0
            with open(local, "wb") as handle:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    total += len(chunk)
                    if total > upload_max_bytes():
                        raise HTTPException(status_code=422, detail="文件过大")
                    handle.write(chunk)
            if size == 0:
                raise HTTPException(status_code=422, detail="不能上传空文件")
            items.append((relative, local, size))
    except HTTPException:
        for _rel, path, _size in items:
            path.unlink(missing_ok=True)
        try:
            temp_root.rmdir()
        except OSError:
            pass
        raise
    _adapter, cookie = open_adapter(session, account, request)
    try:
        task = start_upload(
            session,
            request.app.state.session_factory,
            pan_client(request),
            cookie,
            user.id,
            account.id,
            dest_path,
            items,
        )
    except ValueError as exc:
        for _rel, path, _size in items:
            path.unlink(missing_ok=True)
        try:
            temp_root.rmdir()
        except OSError:
            pass
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return to_upload(task)


@router.get("/api/uploads", response_model=list[UploadTaskOut])
def list_uploads(
    user: User = Depends(get_current_user), session: Session = Depends(get_db)
):
    return [to_upload(row) for row in list_user_uploads(session, user.id)]


@router.post("/api/uploads/{task_id}/cancel", response_model=UploadTaskOut)
def cancel_upload_route(
    task_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    task = get_upload(session, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="上传任务不存在")
    return to_upload(cancel_upload(session, task))


@router.post("/api/transfers", response_model=JobOut, status_code=201)
def create_transfer(
    body: TransferIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    account = owned_drive(session, user, body.account_id)
    try:
        directory = normalize_directory(body.directory)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    label = clean_directory_label(body.directory_label)
    lines = share_chunks(body.links)
    if not lines:
        raise HTTPException(status_code=422, detail="请粘贴分享链接")
    moment = body.now or now_utc()
    if directory != "/":
        cookie = decrypt_cookie(
            account.cookie_ciphertext, get_settings().cookie_fernet_key
        )
        adapter = adapter_for(account.provider, pan_client(request))
        try:
            adapter.list_dir(cookie, directory)
            persist_warmed(session, account, cookie, adapter)
        except LoginRejected as exc:
            account.status = "expired"
            account.updated_at = moment
            session.commit()
            raise HTTPException(
                status_code=422, detail=relogin(account.provider)
            ) from exc
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
        directory_label=label,
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
        elif parsed.provider != account.provider:
            names = {
                "baidu": "请使用百度账号",
                "quark": "请使用夸克账号",
                "xunlei": "请使用迅雷账号",
            }
            status, error = "failed", names.get(parsed.provider, "链接无法解析")
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
def list_jobs(
    user: User = Depends(get_current_user), session: Session = Depends(get_db)
):
    return [
        JobSummaryOut(
            id=job.id,
            type=job.type,
            status=job.status,
            directory=job.directory,
            directory_label=job.directory_label,
            created_at=job.created_at,
            total=total,
            succeeded=succeeded,
            failed=failed,
        )
        for job, total, succeeded, failed in summaries_for_user(session, user.id)
    ]


@router.get("/api/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    job = get_job_for_user(session, user.id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    items = items_for(session, job.id)
    return to_job(job, items)
