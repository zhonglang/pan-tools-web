from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Job, JobItem


def add(session: Session, job: Job) -> Job:
    session.add(job)
    return job


def add_item(session: Session, item: JobItem) -> JobItem:
    session.add(item)
    return item


def list_for_user(session: Session, user_id: int) -> list[Job]:
    return list(session.scalars(select(Job).where(Job.user_id == user_id).order_by(Job.id.desc())).all())


def get_for_user(session: Session, user_id: int, job_id: int) -> Job | None:
    return session.scalar(select(Job).where(Job.id == job_id, Job.user_id == user_id))


def items_for(session: Session, job_id: int) -> list[JobItem]:
    return list(session.scalars(select(JobItem).where(JobItem.job_id == job_id).order_by(JobItem.id)).all())


def running_sync(session: Session, account_id: int) -> Job | None:
    return session.scalar(
        select(Job).where(Job.account_id == account_id, Job.type == "sync", Job.status.in_(("pending", "running")))
    )
