from datetime import datetime

from pydantic import BaseModel


class JobItemOut(BaseModel):
    id: int
    status: str
    input_text: str
    error: str | None
    result: str | None
    attempts: int


class JobOut(BaseModel):
    id: int
    type: str
    status: str
    directory: str
    directory_label: str | None = None
    error: str | None = None
    items: list[JobItemOut]


class JobSummaryOut(BaseModel):
    id: int
    type: str
    status: str
    directory: str
    directory_label: str | None = None
    created_at: datetime
    total: int
    succeeded: int
    failed: int
