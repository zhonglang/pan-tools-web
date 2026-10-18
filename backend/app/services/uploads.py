import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import PanAccount, UploadTask
from app.pans import adapter_for
from app.pans.errors import LoginRejected, PathNotFound, TransferFailed, UploadCancelled

_lock = threading.Lock()
_cancel: set[int] = set()
_account_locks: dict[int, threading.Lock] = {}


def interrupt_upload_orphans(session: Session) -> None:
    rows = session.scalars(select(UploadTask).where(UploadTask.status == "running")).all()
    moment = datetime.now(timezone.utc)
    for row in rows:
        row.status = "failed"
        row.error = "上传已中断"
        row.updated_at = moment
    if rows:
        session.commit()


def upload_max_bytes() -> int:
    return get_settings().upload_max_bytes


def start_upload(
    session: Session,
    session_factory,
    client,
    cookie: str,
    user_id: int,
    account_id: int,
    dest_path: str,
    items: list[tuple[str, Path, int]],
) -> UploadTask:
    if not items:
        raise ValueError("请选择文件")
    total = sum(size for _rel, _path, size in items)
    if total > upload_max_bytes():
        raise ValueError("文件过大")
    task = UploadTask(
        user_id=user_id,
        account_id=account_id,
        dest_path=dest_path,
        name=_task_name(items),
        status="running",
        bytes_done=0,
        bytes_total=total,
        files_done=0,
        files_total=len(items),
    )
    session.add(task)
    session.commit()
    threading.Thread(
        target=_run_upload,
        args=(session_factory, client, task.id, account_id, cookie, dest_path, items),
        daemon=True,
        name=f"upload-{task.id}",
    ).start()
    return task


def cancel_upload(session: Session, task: UploadTask) -> UploadTask:
    if task.status != "running":
        return task
    with _lock:
        _cancel.add(task.id)
    task.status = "cancelled"
    task.updated_at = datetime.now(timezone.utc)
    session.commit()
    return task


def _task_name(items: list[tuple[str, Path, int]]) -> str:
    if len(items) == 1:
        return Path(items[0][0]).name or items[0][1].name
    roots = {Path(rel).parts[0] for rel, _path, _size in items if Path(rel).parts}
    if len(roots) == 1:
        return f"{next(iter(roots))}（{len(items)} 个文件）"
    return f"上传（{len(items)} 个文件）"


def _account_lock(account_id: int) -> threading.Lock:
    with _lock:
        lock = _account_locks.get(account_id)
        if lock is None:
            lock = threading.Lock()
            _account_locks[account_id] = lock
        return lock


def _run_upload(
    session_factory,
    client,
    task_id: int,
    account_id: int,
    cookie: str,
    dest_path: str,
    items: list[tuple[str, Path, int]],
) -> None:
    with session_factory() as session:
        account = session.get(PanAccount, account_id)
        provider = account.provider if account is not None else "baidu"
    adapter = adapter_for(provider, client)
    try:
        with _account_lock(account_id):
            for relative, local_path, size in items:
                if _stopped(task_id):
                    _finish(session_factory, task_id, "cancelled")
                    return
                relative = relative.replace("\\", "/").lstrip("/")
                parent_rel = str(Path(relative).parent).replace("\\", "/")
                if parent_rel in {".", ""}:
                    parent_rel = ""
                filename = Path(relative).name or local_path.name
                _update(session_factory, task_id, current_name=filename)
                target_dir = adapter.ensure_subdir(cookie, dest_path, parent_rel)
                if _stopped(task_id):
                    _finish(session_factory, task_id, "cancelled")
                    return

                def on_progress(delta: int, *, _task_id: int = task_id) -> None:
                    if delta:
                        _bump_bytes(session_factory, _task_id, delta)

                with open(local_path, "rb") as stream:
                    adapter.upload_file(
                        cookie,
                        target_dir,
                        filename,
                        stream,
                        size,
                        on_progress=on_progress,
                        should_stop=lambda: _stopped(task_id),
                    )
                _bump_files(session_factory, task_id)
            _finish(session_factory, task_id, "done", current_name=None)
    except UploadCancelled:
        _finish(session_factory, task_id, "cancelled")
    except PathNotFound:
        _finish(session_factory, task_id, "failed", error="目标目录不存在")
    except LoginRejected:
        _expire(session_factory, account_id)
        _finish(session_factory, task_id, "failed", error="登录已失效，请重新登录")
    except (TransferFailed, OSError, ValueError) as exc:
        message = str(exc).strip()
        if not message or message in {"TransferFailed()", "上传尚未实现"}:
            message = "上传失败"
        _finish(session_factory, task_id, "failed", error=message)
    finally:
        for _rel, local_path, _size in items:
            try:
                os.unlink(local_path)
            except OSError:
                pass
            try:
                parent = local_path.parent
                if parent.name.startswith("pan-upload-"):
                    parent.rmdir()
            except OSError:
                pass
        with _lock:
            _cancel.discard(task_id)


def _stopped(task_id: int) -> bool:
    with _lock:
        return task_id in _cancel


def _update(session_factory, task_id: int, **fields) -> None:
    _write(session_factory, task_id, **fields)


def _bump_bytes(session_factory, task_id: int, delta: int) -> None:
    with session_factory() as session:
        task = session.get(UploadTask, task_id)
        if task is None or task.status != "running":
            return
        task.bytes_done = min(task.bytes_total, task.bytes_done + delta)
        task.updated_at = datetime.now(timezone.utc)
        session.commit()


def _bump_files(session_factory, task_id: int) -> None:
    with session_factory() as session:
        task = session.get(UploadTask, task_id)
        if task is None or task.status != "running":
            return
        task.files_done = min(task.files_total, task.files_done + 1)
        task.updated_at = datetime.now(timezone.utc)
        session.commit()


def _finish(session_factory, task_id: int, status: str, **fields) -> None:
    _write(session_factory, task_id, status=status, **fields)


def _write(session_factory, task_id: int, **fields) -> None:
    with session_factory() as session:
        session.execute(
            update(UploadTask)
            .where(UploadTask.id == task_id, UploadTask.status == "running")
            .values(updated_at=datetime.now(timezone.utc), **fields)
        )
        session.commit()


def _expire(session_factory, account_id: int) -> None:
    with session_factory() as session:
        account = session.get(PanAccount, account_id)
        if account is None:
            return
        account.status = "expired"
        account.updated_at = datetime.now(timezone.utc)
        session.commit()
