import threading
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.services.folder_download import FolderTooLarge, archive_entries
from app.services.local_folder import DownloadCancelled, download_root, write_entries
from app.models import DownloadTask, PanAccount
from app.pans import adapter_for
from app.pans.errors import LoginRejected, PathNotFound, TransferFailed

_lock = threading.Lock()
_cancel: set[int] = set()


def interrupt_orphans(session: Session) -> None:
    rows = session.scalars(
        select(DownloadTask).where(DownloadTask.status == "running")
    ).all()
    moment = datetime.now(timezone.utc)
    for row in rows:
        row.status = "failed"
        row.error = "下载已中断"
        row.updated_at = moment
    if rows:
        session.commit()


def start_save(
    session: Session,
    session_factory,
    client,
    cookie: str,
    user_id: int,
    account_id: int,
    target: str,
) -> DownloadTask:
    task = DownloadTask(
        user_id=user_id,
        account_id=account_id,
        path=target,
        name=target.rstrip("/").rsplit("/", 1)[-1],
        status="running",
        phase="list",
    )
    session.add(task)
    session.commit()
    threading.Thread(
        target=_run_save,
        args=(session_factory, client, task.id, account_id, cookie, target),
        daemon=True,
        name=f"download-{task.id}",
    ).start()
    return task


def cancel_save(session: Session, task: DownloadTask) -> DownloadTask:
    if task.status != "running":
        return task
    with _lock:
        _cancel.add(task.id)
    task.status = "cancelled"
    task.updated_at = datetime.now(timezone.utc)
    session.commit()
    return task


def _run_save(
    session_factory, client, task_id: int, account_id: int, cookie: str, target: str
) -> None:
    with session_factory() as session:
        account = session.get(PanAccount, account_id)
        provider = account.provider if account is not None else "baidu"
    adapter = adapter_for(provider, client)
    try:
        if _stopped(task_id):
            _finish(session_factory, task_id, "cancelled")
            return
        planned = archive_entries(adapter, cookie, target)
        files = [
            (name, remote, size) for name, remote, size in planned if remote is not None
        ]
        _update(
            session_factory,
            task_id,
            phase="save",
            bytes_total=sum(size for _name, _remote, size in files),
            files_total=len(files),
        )
        directory = write_entries(
            adapter,
            cookie,
            target,
            download_root(),
            planned,
            lambda written, files_done, current: _update(
                session_factory,
                task_id,
                bytes_done=written,
                files_done=files_done,
                current_name=current,
            ),
            lambda: _stopped(task_id),
        )
        _finish(
            session_factory, task_id, "done", directory=directory, current_name=None
        )
    except DownloadCancelled:
        _finish(session_factory, task_id, "cancelled")
    except FolderTooLarge:
        _finish(
            session_factory,
            task_id,
            "failed",
            error="目录里的文件太多，请进入下一级再下载",
        )
    except PathNotFound:
        _finish(session_factory, task_id, "failed", error="目标目录不存在")
    except LoginRejected:
        _expire(session_factory, account_id)
        _finish(session_factory, task_id, "failed", error="请重新登录百度")
    except (TransferFailed, OSError):
        _finish(session_factory, task_id, "failed", error="下载失败")
    finally:
        with _lock:
            _cancel.discard(task_id)


def _stopped(task_id: int) -> bool:
    with _lock:
        return task_id in _cancel


def _update(session_factory, task_id: int, **fields) -> None:
    _write(session_factory, task_id, **fields)


def _finish(session_factory, task_id: int, status: str, **fields) -> None:
    _write(session_factory, task_id, status=status, **fields)


def _write(session_factory, task_id: int, **fields) -> None:
    with session_factory() as session:
        session.execute(
            update(DownloadTask)
            .where(DownloadTask.id == task_id, DownloadTask.status == "running")
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
