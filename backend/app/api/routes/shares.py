import json
import secrets
import string

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_cookie
from app.core.deps import get_current_user, get_db, now_utc
from app.crud.jobs import add as add_job
from app.crud.jobs import add_item, get_for_user as get_job_for_user
from app.crud.shares import list_for_job
from app.models import Job, JobItem, User
from app.services.membership import can_use_paid_features
from app.pans import adapter_for
from app.pans.errors import LoginRejected, PathNotFound
from app.services.quota import PaidRequired, reserve_shares
from app.api.routes.transfers import owned_drive, pan_client, relogin, to_job
from app.schemas import JobOut, ShareBatchIn
from app.services.shares import shares_xlsx
from app.services.transfers import clean_directory_label, normalize_directory

router = APIRouter()
_PASSWORD = string.ascii_letters + string.digits
PAID_ONLY = "该功能仅对付费会员开放"


def _parent(path: str) -> str:
    parent = path.rsplit("/", 1)[0]
    return parent or "/"


def _in_current_directory(provider: str, directory: str, path: str, listed: set[str] | None) -> bool:
    if ".." in path.split("/"):
        return False
    if provider in {"quark", "xunlei"} and directory != "/":
        return listed is not None and path in listed
    return _parent(path) == directory


def _password(shared: str | None) -> str:
    if shared:
        return shared
    return "".join(secrets.choice(_PASSWORD) for _ in range(4))


@router.post("/api/shares", response_model=JobOut, status_code=201)
def create_share_job(
    body: ShareBatchIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    if not can_use_paid_features(user, now_utc()):
        raise HTTPException(status_code=403, detail=PAID_ONLY)
    account = owned_drive(session, user, body.account_id)
    try:
        directory = normalize_directory(body.directory)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    label = clean_directory_label(body.directory_label)
    if body.period not in {0, 1, 7, 30}:
        raise HTTPException(status_code=422, detail="有效期无效")
    if body.visibility == "public" and account.provider == "baidu":
        raise HTTPException(status_code=422, detail="百度网盘不支持公开链接")
    if account.provider == "xunlei" or body.visibility == "public":
        item_password = ""
    else:
        shared = (body.password or "").strip() or None
        if shared is not None and (len(shared) != 4 or any(char not in _PASSWORD for char in shared)):
            raise HTTPException(status_code=422, detail="提取码需要 4 位字母或数字")
        item_password = _password(shared)
    if not body.targets:
        raise HTTPException(status_code=422, detail="请选择要分享的文件")
    moment = now_utc()
    listed: set[str] | None = None
    if directory != "/":
        cookie = decrypt_cookie(account.cookie_ciphertext, get_settings().cookie_fernet_key)
        try:
            rows = adapter_for(account.provider, pan_client(request)).list_dir(cookie, directory)
            listed = {row.path for row in rows}
        except LoginRejected as exc:
            account.status = "expired"
            account.updated_at = moment
            session.commit()
            raise HTTPException(status_code=422, detail=relogin(account.provider)) from exc
        except PathNotFound as exc:
            raise HTTPException(status_code=422, detail="目标目录不存在") from exc
    for target in body.targets:
        if not _in_current_directory(account.provider, directory, target.path, listed):
            raise HTTPException(status_code=422, detail="只能分享当前目录中的项目")
    try:
        reserve_shares(session, user, moment, len(body.targets))
    except PaidRequired as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    job = Job(
        user_id=user.id,
        account_id=account.id,
        type="share",
        status="pending",
        directory=directory,
        directory_label=label,
        created_at=moment,
        updated_at=moment,
    )
    add_job(session, job)
    session.flush()
    items: list[JobItem] = []
    for target in body.targets:
        item = JobItem(
            job_id=job.id,
            input_text=json.dumps(
                {
                    "fs_id": target.fs_id,
                    "path": target.path,
                    "name": target.name,
                    "password": item_password,
                    "period": str(body.period),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            status="pending",
            attempts=0,
            created_at=moment,
            updated_at=moment,
        )
        add_item(session, item)
        items.append(item)
    session.commit()
    return to_job(job, items)


@router.get("/api/jobs/{job_id}/export")
def export_share_job(
    job_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    if not can_use_paid_features(user, now_utc()):
        raise HTTPException(status_code=403, detail=PAID_ONLY)
    job = get_job_for_user(session, user.id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.type != "share":
        raise HTTPException(status_code=422, detail="这个任务不能导出")
    rows = list_for_job(session, job.id, status="active")
    return Response(
        content=shares_xlsx(rows),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="shares-{job.id}.xlsx"'},
    )
