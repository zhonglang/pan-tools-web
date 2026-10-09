from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import User
from app.core.security import hash_password


def ensure_admin(session: Session, settings: Settings) -> None:
    existing = session.scalar(select(User).where(User.role == "admin"))
    if existing is not None:
        return
    email = settings.admin_email.lower()
    email_taken = session.scalar(select(User).where(User.email == email))
    if email_taken is not None:
        raise RuntimeError(f"无法创建管理员：邮箱 {email} 已被占用")
    session.add(
        User(
            email=email,
            password_hash=hash_password(settings.admin_password),
            role="admin",
            plan="free",
            plan_expires_at=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    session.commit()
