from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import User


def get(session: Session, user_id: int) -> User | None:
    return session.get(User, user_id)


def get_by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(func.lower(User.email) == email.lower()))


def list_all(session: Session) -> list[User]:
    return list(session.scalars(select(User).order_by(User.id)).all())


def add(session: Session, user: User) -> User:
    session.add(user)
    session.commit()
    session.refresh(user)
    return user
