import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.database import Base
from app.models import PanAccount, UploadTask, User
from app.pans.errors import TransferFailed, UploadCancelled
from app.services import uploads as uploads_service


class FakeAdapter:
    def __init__(self, *, delay: float = 0, fail: bool = False):
        self.dirs: list[tuple[str, str]] = []
        self.files: list[tuple[str, str, bytes]] = []
        self.delay = delay
        self.fail = fail

    def ensure_subdir(self, cookie: str, dest: str, relative_dir: str) -> str:
        self.dirs.append((dest, relative_dir))
        if relative_dir:
            return f"{dest.rstrip('/')}/{relative_dir}"
        return dest

    def upload_file(
        self,
        cookie: str,
        dest_dir: str,
        filename: str,
        stream,
        size: int,
        *,
        on_progress=None,
        should_stop=None,
    ) -> None:
        if self.delay:
            deadline = time.time() + self.delay
            while time.time() < deadline:
                if should_stop and should_stop():
                    raise UploadCancelled()
                time.sleep(0.02)
        if self.fail:
            raise TransferFailed("网盘拒绝")
        data = stream.read()
        if on_progress:
            on_progress(len(data))
        self.files.append((dest_dir, filename, data))


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-at-least-32-bytes-long")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-pass-123")
    monkeypatch.setenv("COOKIE_FERNET_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=")
    get_settings.cache_clear()
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'upload.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        user = User(email="u@example.com", password_hash="h", role="user", plan="paid")
        session.add(user)
        session.commit()
        account = PanAccount(
            user_id=user.id,
            provider="baidu",
            nickname="盘",
            cookie_ciphertext="x",
            status="valid",
        )
        session.add(account)
        session.commit()
        user_id, account_id = user.id, account.id
    yield factory, user_id, account_id
    get_settings.cache_clear()


def _wait(factory, task_id: int, *, timeout: float = 2.0) -> UploadTask:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with factory() as session:
            task = session.get(UploadTask, task_id)
            assert task is not None
            if task.status != "running":
                return task
        time.sleep(0.02)
    with factory() as session:
        return session.get(UploadTask, task_id)


def test_start_upload_completes(db, tmp_path, monkeypatch):
    factory, user_id, account_id = db
    fake = FakeAdapter()
    monkeypatch.setattr(uploads_service, "adapter_for", lambda provider, client: fake)
    local = tmp_path / "a.txt"
    local.write_bytes(b"hello")
    with factory() as session:
        task = uploads_service.start_upload(
            session,
            factory,
            client=None,
            cookie="ck",
            user_id=user_id,
            account_id=account_id,
            dest_path="/测试",
            items=[("a.txt", local, 5)],
        )
        task_id = task.id
    done = _wait(factory, task_id)
    assert done.status == "done"
    assert done.bytes_done == 5
    assert done.files_done == 1
    assert fake.files == [("/测试", "a.txt", b"hello")]


def test_cancel_upload_midway(db, tmp_path, monkeypatch):
    factory, user_id, account_id = db
    fake = FakeAdapter(delay=1.0)
    monkeypatch.setattr(uploads_service, "adapter_for", lambda provider, client: fake)
    local = tmp_path / "slow.txt"
    local.write_bytes(b"data")
    with factory() as session:
        task = uploads_service.start_upload(
            session,
            factory,
            client=None,
            cookie="ck",
            user_id=user_id,
            account_id=account_id,
            dest_path="/",
            items=[("slow.txt", local, 4)],
        )
        task_id = task.id
    time.sleep(0.05)
    with factory() as session:
        row = session.get(UploadTask, task_id)
        uploads_service.cancel_upload(session, row)
    done = _wait(factory, task_id)
    assert done.status == "cancelled"


def test_rejects_oversized(db, tmp_path, monkeypatch):
    factory, user_id, account_id = db
    monkeypatch.setattr(uploads_service, "upload_max_bytes", lambda: 10)
    local = tmp_path / "big.txt"
    local.write_bytes(b"01234567890123456789")
    with factory() as session:
        with pytest.raises(ValueError, match="文件过大"):
            uploads_service.start_upload(
                session,
                factory,
                client=None,
                cookie="ck",
                user_id=user_id,
                account_id=account_id,
                dest_path="/",
                items=[("big.txt", local, 20)],
            )


def test_interrupt_upload_orphans(db):
    factory, user_id, account_id = db
    with factory() as session:
        session.add(
            UploadTask(
                user_id=user_id,
                account_id=account_id,
                dest_path="/",
                name="残留",
                status="running",
                bytes_done=0,
                bytes_total=1,
                files_done=0,
                files_total=1,
            )
        )
        session.commit()
        uploads_service.interrupt_upload_orphans(session)
        row = session.scalars(select(UploadTask)).one()
        assert row.status == "failed"
        assert row.error == "上传已中断"
