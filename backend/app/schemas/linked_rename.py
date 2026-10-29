from pydantic import BaseModel, Field


class LinkedRenameMemberIn(BaseModel):
    account_id: int
    directory: str = Field(min_length=1, max_length=1024)
    label: str = Field(default="", max_length=512)
    is_primary: bool = False
    sort_order: int = 0


class LinkedRenameConfigIn(BaseModel):
    members: list[LinkedRenameMemberIn] = Field(max_length=20)


class LinkedRenameMemberOut(BaseModel):
    id: int
    account_id: int
    directory: str
    label: str
    is_primary: bool
    sort_order: int


class LinkedRenameConfigOut(BaseModel):
    members: list[LinkedRenameMemberOut]


class LinkedRenameIn(BaseModel):
    account_id: int
    path: str = Field(min_length=1, max_length=2048)
    current_name: str = Field(min_length=1, max_length=512)
    name: str = Field(min_length=1, max_length=512)


class LinkedRenameOut(BaseModel):
    renamed: int
    skipped: int
    failed: int
    errors: list[str] = Field(default_factory=list)
