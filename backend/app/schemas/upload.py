from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UploadTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    dest_path: str
    name: str
    status: str
    bytes_done: int
    bytes_total: int
    files_done: int
    files_total: int
    current_name: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime
