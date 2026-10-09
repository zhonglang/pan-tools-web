from datetime import datetime

from pydantic import BaseModel, Field


class TransferIn(BaseModel):
    account_id: int
    directory: str = Field(min_length=1, max_length=1024)
    links: str = Field(min_length=1, max_length=20000)
    now: datetime | None = None


class CreateFolderIn(BaseModel):
    directory: str = Field(min_length=1, max_length=1024)
    name: str = Field(min_length=1, max_length=255)


class DirEntryOut(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    modified_at: int | None = None
    fs_id: int | None = None


class FilePathIn(BaseModel):
    path: str = Field(min_length=1, max_length=1024)


class RenameIn(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    name: str = Field(min_length=1, max_length=255)


class ShareIn(BaseModel):
    fs_id: int


class ShareOut(BaseModel):
    url: str
    password: str


class OkOut(BaseModel):
    ok: bool = True
