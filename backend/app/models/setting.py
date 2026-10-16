from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ShareSetting(Base):
    __tablename__ = "share_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    baidu_password: Mapped[str | None] = mapped_column(String(4), nullable=True)
    quark_password: Mapped[str | None] = mapped_column(String(4), nullable=True)
    xunlei_password: Mapped[str | None] = mapped_column(String(4), nullable=True)
