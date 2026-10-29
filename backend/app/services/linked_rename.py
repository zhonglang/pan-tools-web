from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.linked_rename import LinkedRenameMember
from app.services.library import apply_episode_from_folder_name, split_prefixed_name
from app.services.transfers import normalize_directory


@dataclass
class MemberDraft:
    account_id: int
    directory: str
    label: str
    is_primary: bool
    sort_order: int


@dataclass
class LinkedRenameResult:
    renamed: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def prefix_key(name: str) -> int | None:
    parts = split_prefixed_name(name)
    if parts is None:
        return None
    return int(parts[0])


def list_members(session: Session, user_id: int) -> list[LinkedRenameMember]:
    return list(
        session.scalars(
            select(LinkedRenameMember)
            .where(LinkedRenameMember.user_id == user_id)
            .order_by(
                LinkedRenameMember.is_primary.desc(),
                LinkedRenameMember.sort_order,
                LinkedRenameMember.id,
            )
        )
    )


def replace_members(
    session: Session, user_id: int, drafts: list[MemberDraft]
) -> list[LinkedRenameMember]:
    session.execute(
        delete(LinkedRenameMember).where(LinkedRenameMember.user_id == user_id)
    )
    now = datetime.now(timezone.utc)
    for index, draft in enumerate(drafts):
        session.add(
            LinkedRenameMember(
                user_id=user_id,
                account_id=draft.account_id,
                directory=normalize_directory(draft.directory),
                label=(draft.label or "").strip(),
                is_primary=bool(draft.is_primary),
                sort_order=draft.sort_order if draft.sort_order else index,
                created_at=now,
                updated_at=now,
            )
        )
    session.flush()
    return list_members(session, user_id)


def primary_member(members: list[LinkedRenameMember]) -> LinkedRenameMember | None:
    for row in members:
        if row.is_primary:
            return row
    return None


DirLister = Callable[
    [int, str], list[tuple[str, str]]
]  # account_id, directory -> [(path, name)]
Renamer = Callable[[int, str, str], None]  # account_id, path, new_name


def _rename_peer(
    peer: LinkedRenameMember,
    *,
    key: int,
    new_name: str,
    list_folders: DirLister,
    rename: Renamer,
) -> tuple[str, str | None]:
    try:
        folders = list_folders(peer.account_id, peer.directory)
    except Exception as exc:  # noqa: BLE001 - surface as failed peer
        return "failed", f"账号 {peer.account_id}：{exc}"
    match = next((item for item in folders if prefix_key(item[1]) == key), None)
    if match is None:
        return "skipped", None
    peer_path, peer_name = match
    if peer_name == new_name:
        return "skipped", None
    try:
        rename(peer.account_id, peer_path, new_name)
        return "renamed", None
    except Exception as exc:  # noqa: BLE001
        return "failed", f"{peer_name}：{exc}"


def linked_rename(
    session: Session,
    user_id: int,
    *,
    account_id: int,
    path: str,
    current_name: str,
    new_name: str,
    list_folders: DirLister,
    rename: Renamer,
) -> LinkedRenameResult:
    members = list_members(session, user_id)
    primary = primary_member(members)
    if primary is None:
        raise ValueError("请先在系统配置中设置关联重命名主目录")
    if primary.account_id != account_id:
        raise ValueError("只能从主网盘目录发起关联重命名")

    key = prefix_key(current_name)
    if key is None:
        raise ValueError("文件名需要以数字序号开头才能关联重命名")

    result = LinkedRenameResult()
    rename(account_id, path, new_name)
    result.renamed += 1
    apply_episode_from_folder_name(session, user_id, new_name)

    peers = [row for row in members if not row.is_primary]
    if not peers:
        return result

    workers = min(8, len(peers))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                _rename_peer,
                peer,
                key=key,
                new_name=new_name,
                list_folders=list_folders,
                rename=rename,
            )
            for peer in peers
        ]
        for future in as_completed(futures):
            status, error = future.result()
            if status == "renamed":
                result.renamed += 1
            elif status == "skipped":
                result.skipped += 1
            else:
                result.failed += 1
                if error:
                    result.errors.append(error)
    return result
