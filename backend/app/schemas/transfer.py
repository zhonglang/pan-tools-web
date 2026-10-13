from datetime import datetime

from pydantic import BaseModel, Field


class TransferIn(BaseModel):
    account_id: int
    directory: str = Field(min_length=1, max_length=1024)
    directory_label: str | None = Field(default=None, max_length=1024)
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
    created_at: int | None = None
    modified_at: int | None = None
    fs_id: int | None = None


class FilePathIn(BaseModel):
    path: str = Field(min_length=1, max_length=1024)


class RenameIn(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    name: str = Field(min_length=1, max_length=255)


class ShareIn(BaseModel):
    fs_id: int | None = None
    path: str | None = None
    name: str | None = None


class ShareOut(BaseModel):
    url: str
    password: str


class OkOut(BaseModel):
    ok: bool = True


class CopyIn(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    fs_id: int | None = None
    name: str = Field(min_length=1, max_length=255)
    is_dir: bool = False
    targets: list[str] = Field(min_length=1, max_length=50)


class CopyTargetResultOut(BaseModel):
    path: str
    name: str
    ok: bool
    error: str | None = None


class CopyOut(BaseModel):
    succeeded: int
    failed: int
    results: list[CopyTargetResultOut]
