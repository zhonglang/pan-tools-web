from datetime import datetime

from pydantic import BaseModel


class MetricOut(BaseModel):
    value: int | None
    from_time: datetime | None = None


class RankRowOut(BaseModel):
    name: str
    account_name: str
    url: str
    created_at: datetime
    views: int | None
    transfers: int | None
    downloads: int | None


class SeriesLineOut(BaseModel):
    account_id: int
    account_name: str
    values: list[int | None]


class CreatedSharesOut(BaseModel):
    page: int
    page_size: int
    total: int
    rows: list[RankRowOut]


class StatsOut(BaseModel):
    total: int
    first_snapshot_at: datetime | None
    range_start: datetime | None = None
    range_end: datetime | None = None
    new_shares: int
    views: MetricOut
    transfers: MetricOut
    downloads: MetricOut
    rank: str
    page: int
    page_size: int
    rank_total: int
    rows: list[RankRowOut]
    dates: list[str] = []
    lines: list[SeriesLineOut] = []
