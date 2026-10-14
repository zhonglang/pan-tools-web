from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ShareLink(Base):
    __tablename__ = "share_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("pan_accounts.id"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    baidu_share_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(String(1024))
    url: Mapped[str] = mapped_column(Text)
    password: Mapped[str | None] = mapped_column(String(16), nullable=True)
    expired: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="active")
    view_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transfer_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    download_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ShareStatSnapshot(Base):
    __tablename__ = "share_stat_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    share_link_id: Mapped[int] = mapped_column(ForeignKey("share_links.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("pan_accounts.id"), index=True)
    view_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transfer_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    download_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AccountStatDay(Base):
    __tablename__ = "account_stat_days"
    __table_args__ = (UniqueConstraint("account_id", "stat_date", name="uq_account_stat_days_account_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("pan_accounts.id"), index=True)
    stat_date: Mapped[date] = mapped_column(Date)
    transfer_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    view_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    download_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    link_total: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
