from pydantic import BaseModel, Field


class LibraryItemOut(BaseModel):
    id: int
    prefix: str
    name: str
    finished: bool = False
    latest_episode: int | None = None
    previous_episode: int | None = None
    xunlei_url: str
    quark_url: str
    baidu_url: str
    updated_at: str | None = None


class LibraryImportRowIn(BaseModel):
    name: str = Field(default="", max_length=512)
    url: str = Field(default="", max_length=4000)
    password: str = Field(default="", max_length=32)


class LibraryImportIn(BaseModel):
    rows: list[LibraryImportRowIn] = Field(max_length=5000)


class LibraryImportOut(BaseModel):
    created: int
    updated: int
    skipped: int
    items: list[LibraryItemOut]


class LibraryCheckHit(BaseModel):
    id: int
    prefix: str
    name: str
    provider: str
    reason: str


class LibraryCheckOut(BaseModel):
    checked: int
    invalid: list[LibraryCheckHit]
    unknown: int


class LibraryItemIn(BaseModel):
    name: str = Field(default="", max_length=512)
    finished: bool = False
    latest_episode: int | None = None
    xunlei_url: str = Field(default="", max_length=4000)
    quark_url: str = Field(default="", max_length=4000)
    baidu_url: str = Field(default="", max_length=4000)


class LibraryCreateIn(BaseModel):
    prefix: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=512)
    finished: bool = False
    latest_episode: int | None = None
    xunlei_url: str = Field(default="", max_length=4000)
    quark_url: str = Field(default="", max_length=4000)
    baidu_url: str = Field(default="", max_length=4000)
