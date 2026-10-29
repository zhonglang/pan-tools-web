from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import Job, JobItem


def add(session: Session, job: Job) -> Job:
    session.add(job)
    return job


def add_item(session: Session, item: JobItem) -> JobItem:
    session.add(item)
    return item


def list_for_user(session: Session, user_id: int) -> list[Job]:
    return list(
        session.scalars(
            select(Job).where(Job.user_id == user_id).order_by(Job.id.desc())
        ).all()
    )


def summaries_for_user(
    session: Session, user_id: int
) -> list[tuple[Job, int, int, int]]:
    """Return (job, total, succeeded, failed) without N+1 item loads."""
    counts = (
        select(
            JobItem.job_id.label("job_id"),
            func.count().label("total"),
            func.coalesce(
                func.sum(case((JobItem.status == "succeeded", 1), else_=0)), 0
            ).label("succeeded"),
            func.coalesce(
                func.sum(case((JobItem.status == "failed", 1), else_=0)), 0
            ).label("failed"),
        )
        .group_by(JobItem.job_id)
        .subquery()
    )
    rows = session.execute(
        select(Job, counts.c.total, counts.c.succeeded, counts.c.failed)
        .outerjoin(counts, counts.c.job_id == Job.id)
        .where(Job.user_id == user_id)
        .order_by(Job.id.desc())
    ).all()
    return [
        (job, int(total or 0), int(succeeded or 0), int(failed or 0))
        for job, total, succeeded, failed in rows
    ]


def get_for_user(session: Session, user_id: int, job_id: int) -> Job | None:
    return session.scalar(select(Job).where(Job.id == job_id, Job.user_id == user_id))


def items_for(session: Session, job_id: int) -> list[JobItem]:
    return list(
        session.scalars(
            select(JobItem).where(JobItem.job_id == job_id).order_by(JobItem.id)
        ).all()
    )


def running_sync(session: Session, account_id: int) -> Job | None:
    return session.scalar(
        select(Job).where(
            Job.account_id == account_id,
            Job.type == "sync",
            Job.status.in_(("pending", "running")),
        )
    )
