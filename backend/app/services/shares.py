import io
import json
import re
from collections.abc import Callable
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_cookie
from app.services.transfers import keep_warmed
from app.models import Job, JobItem, PanAccount, ShareLink
from app.pans import adapter_for
from app.pans.errors import LoginRejected, RateLimited, TransferFailed
from app.services.transfers import EXPIRED, RETRY_DELAYS, fail_remaining, finish_job, publish

_SHARE_ID = re.compile(r"/s/1([0-9A-Za-z_-]+)")


def load_target(raw: str) -> dict:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("条目无效")
    fs_id = data.get("fs_id")
    path = data.get("path")
    name = data.get("name")
    password = data.get("password")
    period = data.get("period")
    if fs_id is not None and not isinstance(fs_id, int):
        raise ValueError("条目无效")
    if not isinstance(path, str) or not isinstance(name, str):
        raise ValueError("条目无效")
    if not isinstance(password, str) or not isinstance(period, str):
        raise ValueError("条目无效")
    return data


def execute_share(
    session: Session,
    client,
    job: Job,
    sleeper: Callable[[float], None],
    now: datetime,
) -> None:
    from sqlalchemy import select

    job.status = "running"
    job.updated_at = now
    publish(session)
    account = session.get(PanAccount, job.account_id)
    items = session.scalars(select(JobItem).where(JobItem.job_id == job.id).order_by(JobItem.id)).all()
    if account is None or account.status != "valid":
        fail_remaining(items, 0, now)
        finish_job(job, items, now)
        publish(session)
        return
    cookie = decrypt_cookie(account.cookie_ciphertext, get_settings().cookie_fernet_key)
    adapter = adapter_for(account.provider, client)
    for index, item in enumerate(items):
        if item.status != "pending":
            continue
        outcome = _run_share(session, adapter, item, account, job, cookie, sleeper, now)
        cookie = keep_warmed(session, account, adapter, cookie)
        publish(session)
        if outcome == "expired":
            fail_remaining(items, index + 1, now)
            break
    finish_job(job, items, now)
    publish(session)


def _run_share(session, adapter, item, account, job, cookie, sleeper, now) -> str:
    try:
        target = load_target(item.input_text)
    except (ValueError, json.JSONDecodeError):
        item.status = "failed"
        item.error = "条目无效"
        item.updated_at = now
        return "failed"
    while item.attempts < 3:
        item.attempts += 1
        item.status = "running"
        item.updated_at = now
        try:
            created = adapter.create_share(
                cookie,
                target.get("fs_id"),
                target["password"],
                target["period"],
                path=target["path"],
                name=target["name"],
            )
            if isinstance(created, tuple):
                link, share_password = created
            else:
                link, share_password = created, target["password"]
        except RateLimited:
            if item.attempts >= 3:
                item.status = "failed"
                item.error = "分享失败"
                item.updated_at = now
                return "failed"
            sleeper(RETRY_DELAYS[item.attempts - 1])
            continue
        except LoginRejected:
            account.status = "expired"
            account.updated_at = now
            item.status = "failed"
            item.error = EXPIRED
            item.updated_at = now
            return "expired"
        except TransferFailed:
            item.status = "failed"
            item.error = "分享失败"
            item.updated_at = now
            return "failed"
        matched = _SHARE_ID.search(link)
        session.add(
            ShareLink(
                user_id=job.user_id,
                account_id=job.account_id,
                job_id=job.id,
                baidu_share_id=matched.group(1) if matched else None,
                name=target["name"],
                path=target["path"],
                url=link,
                password=share_password or None,
                expired=False,
                status="active",
                created_at=now,
            )
        )
        item.status = "succeeded"
        item.result = link
        item.error = None
        item.updated_at = now
        return "succeeded"
    item.status = "failed"
    item.error = "分享失败"
    item.updated_at = now
    return "failed"


def shares_xlsx(rows: list[ShareLink]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    book = Workbook()
    sheet = book.active
    sheet.title = "分享链接"
    sheet.append(["名称", "分享链接", "提取码"])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append([row.name, row.url, row.password or ""])
    sheet.column_dimensions["A"].width = 36
    sheet.column_dimensions["B"].width = 64
    sheet.column_dimensions["C"].width = 14
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()

