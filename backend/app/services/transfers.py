from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_cookie, encrypt_cookie
from app.services.links import parse_share_link
from app.models import Job, JobItem, PanAccount
from app.pans import adapter_for
from app.pans.errors import (
    DuplicateName,
    InvalidLink,
    LoginRejected,
    RateLimited,
    TransferFailed,
    WrongPassword,
)

RETRY_DELAYS = (2, 8, 20)
EXPIRED = "登录已失效，请重新登录"


def normalize_directory(directory: str) -> str:
    cleaned = directory.strip()
    if not cleaned.startswith("/") or ".." in cleaned.split("/"):
        raise ValueError("目标目录无效")
    return cleaned


def clean_directory_label(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def publish(session: Session) -> None:
    session.commit()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def finish_job(job: Job, items: list[JobItem], now: datetime) -> None:
    statuses = {item.status for item in items}
    if statuses == {"succeeded"}:
        job.status = "succeeded"
    elif "succeeded" in statuses:
        job.status = "partial"
    else:
        job.status = "failed"
    job.updated_at = now


def fail_remaining(items: list[JobItem], start: int, now: datetime) -> None:
    for item in items[start:]:
        if item.status == "pending":
            item.status = "failed"
            item.error = EXPIRED
            item.updated_at = now


def keep_warmed(session: Session, account: PanAccount, adapter, cookie: str) -> str:
    warmed = getattr(adapter, "warmed", None)
    if not isinstance(warmed, str) or warmed == cookie:
        return cookie
    account.cookie_ciphertext = encrypt_cookie(warmed, get_settings().cookie_fernet_key)
    return warmed


def _provider_error(provider: str) -> str:
    if provider == "baidu":
        return "请使用百度账号"
    if provider == "quark":
        return "请使用夸克账号"
    if provider == "xunlei":
        return "请使用迅雷账号"
    return "链接无法解析"


def run_item(
    adapter,
    item: JobItem,
    account: PanAccount,
    directory: str,
    cookie: str,
    sleeper: Callable[[float], None],
    now: datetime,
) -> str:
    parsed = parse_share_link(item.input_text)
    if parsed is None or parsed.provider != account.provider:
        item.status = "failed"
        item.error = "链接无法解析" if parsed is None else _provider_error(parsed.provider)
        item.updated_at = now
        return "failed"
    while item.attempts < 3:
        item.attempts += 1
        item.status = "running"
        item.updated_at = now
        try:
            adapter.transfer_share(cookie, parsed.surl, parsed.password, directory)
        except RateLimited:
            if item.attempts >= 3:
                item.status = "failed"
                item.error = "转存失败"
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
        except WrongPassword:
            item.status = "failed"
            item.error = "提取码错误"
            item.updated_at = now
            return "failed"
        except InvalidLink:
            item.status = "failed"
            item.error = "链接无效"
            item.updated_at = now
            return "failed"
        except DuplicateName:
            item.status = "failed"
            item.error = "目标目录已有同名文件"
            item.updated_at = now
            return "failed"
        except TransferFailed:
            item.status = "failed"
            item.error = "转存失败"
            item.updated_at = now
            return "failed"
        item.status = "succeeded"
        item.result = "已转存"
        item.error = None
        item.updated_at = now
        return "succeeded"
    item.status = "failed"
    item.error = "转存失败"
    item.updated_at = now
    return "failed"


def execute_job(session: Session, client, job: Job, sleeper: Callable[[float], None], now: datetime) -> None:
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
        outcome = run_item(adapter, item, account, job.directory, cookie, sleeper, now)
        cookie = keep_warmed(session, account, adapter, cookie)
        publish(session)
        if outcome == "expired":
            fail_remaining(items, index + 1, now)
            break
    finish_job(job, items, now)
    publish(session)


def reclaim_stale(session: Session, now: datetime) -> None:
    cutoff = now - timedelta(minutes=15)
    jobs = session.scalars(select(Job).where(Job.type.in_(("transfer", "share", "sync")), Job.status == "running")).all()
    for job in jobs:
        if job.type == "sync":
            if _aware(job.updated_at) < cutoff:
                job.status = "pending"
                job.updated_at = now
            continue
        items = session.scalars(select(JobItem).where(JobItem.job_id == job.id)).all()
        for item in items:
            if item.status != "running":
                continue
            if _aware(item.updated_at) >= cutoff:
                continue
            if item.attempts >= 3:
                item.status = "failed"
                item.error = "已达到重试上限"
            else:
                item.status = "pending"
            item.updated_at = now
        if any(item.status == "running" for item in items):
            continue
        if any(item.status == "pending" for item in items):
            job.status = "pending"
        else:
            finish_job(job, items, now)
        job.updated_at = now
