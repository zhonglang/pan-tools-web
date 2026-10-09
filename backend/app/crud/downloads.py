from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DownloadTask


def get(session: Session, task_id: int) -> DownloadTask | None:
    return session.get(DownloadTask, task_id)


def list_for_user(session: Session, user_id: int, limit: int = 100) -> list[DownloadTask]:
    return list(
        session.scalars(
            select(DownloadTask).where(DownloadTask.user_id == user_id).order_by(DownloadTask.id.desc()).limit(limit)
        ).all()
    )
