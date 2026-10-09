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
from app.pans.baidu import BaiduAdapter
from app.pans.errors import LoginRejected, PathNotFound
from app.services.quota import PaidRequired, reserve_shares
from app.api.routes.transfers import owned_baidu, pan_client, to_job
from app.schemas import JobOut, ShareBatchIn
from app.services.shares import shares_csv
from app.services.transfers import normalize_directory

router = APIRouter()
_PASSWORD = string.ascii_letters + string.digits
PAID_ONLY = "该功能仅对付费会员开放"


def _parent(path: str) -> str:
    parent = path.rsplit("/", 1)[0]
    return parent or "/"


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
    account = owned_baidu(session, user, body.account_id)
    try:
        directory = normalize_directory(body.directory)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.period not in {0, 1, 7}:
        raise HTTPException(status_code=422, detail="有效期无效")
    shared = (body.password or "").strip() or None
    if shared is not None and (len(shared) != 4 or any(char not in _PASSWORD for char in shared)):
        raise HTTPException(status_code=422, detail="提取码需要 4 位字母或数字")
    if not body.targets:
        raise HTTPException(status_code=422, detail="请选择要分享的文件")
    for target in body.targets:
        if ".." in target.path.split("/") or _parent(target.path) != directory:
            raise HTTPException(status_code=422, detail="只能分享当前目录中的项目")
    moment = now_utc()
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
        reserve_shares(session, user, moment, len(body.targets))
    except PaidRequired as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    job = Job(
        user_id=user.id,
        account_id=account.id,
        type="share",
        status="pending",
        directory=directory,
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
                    "password": _password(shared),
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
        content=shares_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="shares-{job.id}.csv"'},
    )
