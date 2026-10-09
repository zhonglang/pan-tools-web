from datetime import datetime

from pydantic import BaseModel, Field


class AccountBindIn(BaseModel):
    provider: str
    cookie: str = Field(min_length=1, max_length=8192)


class AccountCookieIn(BaseModel):
    cookie: str = Field(min_length=1, max_length=8192)


class AccountOut(BaseModel):
    id: int
    provider: str
    nickname: str
    status: str
    created_at: datetime
    updated_at: datetime


class BaiduLoginStartIn(BaseModel):
    account_id: int | None = None


class BaiduLoginOut(BaseModel):
    id: str
    status: str
    nickname: str | None = None
