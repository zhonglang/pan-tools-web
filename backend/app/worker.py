import time

import httpx
from sqlalchemy import select

from app.bootstrap import ensure_admin
from app.config import get_settings
from app.db import Base, make_engine, make_session_factory
from app.deps import now_utc
from app.models import Job
from app.transfers import execute_job, reclaim_stale


def run_once(session_factory, client: httpx.Client) -> bool:
    now = now_utc()
    with session_factory() as session:
        reclaim_stale(session, now)
        running = session.scalar(select(Job).where(Job.type == "transfer", Job.status == "running"))
        if running is not None:
            session.commit()
            return False
        job = session.scalar(select(Job).where(Job.type == "transfer", Job.status == "pending").order_by(Job.id))
        if job is None:
            session.commit()
            return False
        execute_job(session, client, job, sleeper=time.sleep, now=now)
        session.commit()
        return True


def main() -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    if settings.auto_create_tables:
        Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        ensure_admin(session, settings)
    client = httpx.Client()
    try:
        while True:
            worked = run_once(session_factory, client)
            if not worked:
                time.sleep(2)
    finally:
        client.close()


if __name__ == "__main__":
    main()
