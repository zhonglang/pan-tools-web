from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LibraryItem(Base):
    __tablename__ = "library_items"
    __table_args__ = (UniqueConstraint("user_id", "prefix"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    prefix: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(512), default="")
    finished: Mapped[bool] = mapped_column(Boolean, default=False)
    latest_episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous_episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    xunlei_url: Mapped[str] = mapped_column(Text, default="")
    quark_url: Mapped[str] = mapped_column(Text, default="")
    baidu_url: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
