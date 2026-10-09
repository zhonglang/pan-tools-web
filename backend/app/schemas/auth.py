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
