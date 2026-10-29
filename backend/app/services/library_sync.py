from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.library_sync import LibrarySyncSource
from app.services.library import list_items, parse_folder_label
from app.services.transfers import normalize_directory


@dataclass
class EpisodeSyncHit:
    id: int
    prefix: str
    name: str
    finished: bool
    latest_episode: int | None
    changed: bool


@dataclass
class EpisodeSyncResult:
    updated: int
    unchanged: int
    unmatched: int
    items: list[EpisodeSyncHit]


@dataclass
class SyncSourceDraft:
    account_id: int
    directory: str
    label: str
    sort_order: int


def list_sync_sources(session: Session, user_id: int) -> list[LibrarySyncSource]:
    return list(
        session.scalars(
            select(LibrarySyncSource)
            .where(LibrarySyncSource.user_id == user_id)
            .order_by(LibrarySyncSource.sort_order, LibrarySyncSource.id)
        )
    )


def replace_sync_sources(
    session: Session, user_id: int, drafts: list[SyncSourceDraft]
) -> list[LibrarySyncSource]:
    session.execute(
        delete(LibrarySyncSource).where(LibrarySyncSource.user_id == user_id)
    )
    now = datetime.now(timezone.utc)
    rows: list[LibrarySyncSource] = []
    for index, draft in enumerate(drafts):
        directory = normalize_directory(draft.directory)
        row = LibrarySyncSource(
            user_id=user_id,
            account_id=draft.account_id,
            directory=directory,
            label=(draft.label or "").strip(),
            sort_order=draft.sort_order if draft.sort_order else index,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        rows.append(row)
    session.flush()
    return list_sync_sources(session, user_id)


def sync_episodes(
    session: Session,
    user_id: int,
    *,
    list_folders: Callable[[int, str], list[str]],
) -> EpisodeSyncResult:
    sources = list_sync_sources(session, user_id)
    if not sources:
        raise ValueError("请先在系统配置中添加同步目录")

    by_prefix: dict[str, tuple[bool, int | None]] = {}
    for source in sources:
        for name in list_folders(source.account_id, source.directory):
            parsed = parse_folder_label(name)
            if parsed is None:
                continue
            prefix, _title, finished, latest = parsed
            by_prefix[prefix] = (finished, latest)

    existing = {item.prefix: item for item in list_items(session, user_id)}
    now = datetime.now(timezone.utc)
    updated = 0
    unchanged = 0
    unmatched = 0
    hits: list[EpisodeSyncHit] = []

    for prefix, (finished, latest) in by_prefix.items():
        item = existing.get(prefix)
        if item is None:
            unmatched += 1
            continue
        changed = bool(item.finished) != bool(finished) or item.latest_episode != latest
        if changed:
            if item.latest_episode != latest:
                item.previous_episode = item.latest_episode
            item.finished = bool(finished)
            item.latest_episode = latest
            item.updated_at = now
            updated += 1
        else:
            unchanged += 1
        hits.append(
            EpisodeSyncHit(
                id=item.id,
                prefix=item.prefix,
                name=item.name,
                finished=bool(item.finished),
                latest_episode=item.latest_episode,
                changed=changed,
            )
        )

    hits.sort(
        key=lambda hit: (int(hit.prefix) if hit.prefix.isdigit() else 10**9, hit.prefix)
    )
    return EpisodeSyncResult(
        updated=updated, unchanged=unchanged, unmatched=unmatched, items=hits
    )
