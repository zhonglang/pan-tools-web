from pydantic import BaseModel, Field


class ShareTargetIn(BaseModel):
    fs_id: int | None = None
    path: str = Field(min_length=1, max_length=1024)
    name: str = Field(min_length=1, max_length=255)


class ShareBatchIn(BaseModel):
    account_id: int
    directory: str
    period: int = 0
    password: str | None = None
    targets: list[ShareTargetIn]
