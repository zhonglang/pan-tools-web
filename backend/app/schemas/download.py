from datetime import datetime

from pydantic import BaseModel


class DownloadTaskOut(BaseModel):
    id: int
    account_id: int
    name: str
    path: str
    status: str
    phase: str
    bytes_done: int
    bytes_total: int
    files_done: int
    files_total: int
    current_name: str | None
    directory: str | None
    error: str | None
    created_at: datetime
