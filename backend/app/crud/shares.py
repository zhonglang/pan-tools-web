from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ShareLink


def list_for_job(session: Session, job_id: int, *, status: str | None = None) -> list[ShareLink]:
    query = select(ShareLink).where(ShareLink.job_id == job_id)
    if status is not None:
        query = query.where(ShareLink.status == status)
    return list(session.scalars(query.order_by(ShareLink.id)).all())
