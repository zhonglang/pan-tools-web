from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import User
from app.security import hash_password


def ensure_admin(session: Session, settings: Settings) -> None:
    existing = session.scalar(select(User).where(User.role == "admin"))
    if existing is not None:
        return
    session.add(
        User(
            email=settings.admin_email.lower(),
            password_hash=hash_password(settings.admin_password),
            role="admin",
            plan="free",
            plan_expires_at=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    session.commit()
