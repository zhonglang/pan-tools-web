from typing import Literal

from pydantic import BaseModel, Field


class ShareTargetIn(BaseModel):
    fs_id: int | None = None
    path: str = Field(min_length=1, max_length=1024)
    name: str = Field(min_length=1, max_length=255)


class ShareBatchIn(BaseModel):
    account_id: int
    directory: str
    directory_label: str | None = Field(default=None, max_length=1024)
    period: int = 0
    password: str | None = None
    visibility: Literal["public", "private"] = "private"
    targets: list[ShareTargetIn]


class SharePasswordsOut(BaseModel):
    baidu_password: str | None = None
    quark_password: str | None = None
    xunlei_password: str | None = None


class SharePasswordsIn(BaseModel):
    baidu_password: str | None = Field(default=None, max_length=4)
    quark_password: str | None = Field(default=None, max_length=4)
    xunlei_password: str | None = Field(default=None, max_length=4)
