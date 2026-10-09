from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PanAccount


def get_for_user(session: Session, user_id: int, account_id: int) -> PanAccount | None:
    return session.scalar(select(PanAccount).where(PanAccount.id == account_id, PanAccount.user_id == user_id))


def list_for_user(session: Session, user_id: int) -> list[PanAccount]:
    return list(session.scalars(select(PanAccount).where(PanAccount.user_id == user_id).order_by(PanAccount.id)).all())


def list_baidu(session: Session, user_id: int) -> list[PanAccount]:
    return list(
        session.scalars(select(PanAccount).where(PanAccount.user_id == user_id, PanAccount.provider == "baidu")).all()
    )


def list_drives(session: Session, user_id: int) -> list[PanAccount]:
    return list(
        session.scalars(
            select(PanAccount)
            .where(PanAccount.user_id == user_id, PanAccount.provider.in_(("baidu", "quark")))
            .order_by(PanAccount.id)
        ).all()
    )


def count_valid(session: Session, user_id: int, provider: str) -> int:
    count = session.scalar(
        select(func.count())
        .select_from(PanAccount)
        .where(PanAccount.user_id == user_id, PanAccount.provider == provider, PanAccount.status == "valid")
    )
    return int(count or 0)


def count_valid_baidu(session: Session, user_id: int) -> int:
    return count_valid(session, user_id, "baidu")


def add(session: Session, account: PanAccount) -> PanAccount:
    session.add(account)
    session.commit()
    session.refresh(account)
    return account
