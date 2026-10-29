from pydantic import BaseModel, Field


class LibrarySyncSourceIn(BaseModel):
    account_id: int
    directory: str = Field(min_length=1, max_length=1024)
    label: str = Field(default="", max_length=512)
    sort_order: int = 0


class LibrarySyncSourcesIn(BaseModel):
    sources: list[LibrarySyncSourceIn] = Field(max_length=50)


class LibrarySyncSourceOut(BaseModel):
    id: int
    account_id: int
    directory: str
    label: str
    sort_order: int


class LibraryEpisodeSyncHit(BaseModel):
    id: int
    prefix: str
    name: str
    finished: bool
    latest_episode: int | None
    changed: bool


class LibraryEpisodeSyncOut(BaseModel):
    updated: int
    unchanged: int
    unmatched: int
    items: list[LibraryEpisodeSyncHit]
