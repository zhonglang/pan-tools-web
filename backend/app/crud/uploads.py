from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UploadTask


def get(session: Session, task_id: int) -> UploadTask | None:
    return session.get(UploadTask, task_id)


def list_for_user(session: Session, user_id: int, limit: int = 100) -> list[UploadTask]:
    return list(
        session.scalars(
            select(UploadTask)
            .where(UploadTask.user_id == user_id)
            .order_by(UploadTask.id.desc())
            .limit(limit)
        ).all()
    )
