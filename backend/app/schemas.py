from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    plan: str
    effective_plan: str
    plan_expires_at: datetime | None
    paid_features: bool


class PlanUpdateIn(BaseModel):
    plan: str
    plan_expires_at: datetime | None = None


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


class TransferIn(BaseModel):
    account_id: int
    directory: str = Field(min_length=1, max_length=1024)
    links: str = Field(min_length=1, max_length=20000)
    now: datetime | None = None


class DirEntryOut(BaseModel):
    name: str
    path: str
    is_dir: bool


class JobItemOut(BaseModel):
    id: int
    status: str
    input_text: str
    error: str | None
    result: str | None
    attempts: int


class JobOut(BaseModel):
    id: int
    status: str
    directory: str
    items: list[JobItemOut]
