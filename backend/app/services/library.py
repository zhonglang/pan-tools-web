import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.library import LibraryItem
from app.services.links import parse_share_link

_PREFIX = re.compile(r"^(\d{1,16})(?:\s+|(?=\D)|$)(.*)$")
_FIELDS = {"baidu": "baidu_url", "quark": "quark_url", "xunlei": "xunlei_url"}


@dataclass(frozen=True)
class ImportRow:
    name: str
    url: str
    password: str = ""


@dataclass
class ImportResult:
    created: int
    updated: int
    skipped: int


def split_prefixed_name(name: str) -> tuple[str, str] | None:
    matched = _PREFIX.match(name.strip())
    if matched is None:
        return None
    prefix, title = matched.group(1), matched.group(2).strip()
    if not prefix:
        return None
    return prefix, title


def compose_link(url: str, password: str) -> str | None:
    cleaned = url.strip()
    parsed = parse_share_link(cleaned)
    if parsed is None:
        return None
    code = password.strip()
    if code and "pwd=" not in cleaned and "提取码" not in cleaned:
        return f"{cleaned} 提取码: {code}"
    return cleaned


def list_items(session: Session, user_id: int) -> list[LibraryItem]:
    rows = session.scalars(
        select(LibraryItem).where(LibraryItem.user_id == user_id)
    ).all()
    return sorted(rows, key=lambda item: (int(item.prefix), item.prefix))


def clean_export_name(name: str) -> str:
    text = (name or "").strip()
    text = re.sub(r"^\d+\s*", "", text)
    text = text.split("#", 1)[0]
    return re.sub(r"\s+", " ", text).strip()


def library_xlsx(rows: list[LibraryItem]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    book = Workbook()
    sheet = book.active
    sheet.title = "资源库"
    sheet.append(
        ["名称", "最新一集", "是否完结", "百度网盘链接", "迅雷网盘链接", "夸克网盘链接"]
    )
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append(
            [
                clean_export_name(row.name or ""),
                row.latest_episode,
                "是" if row.finished else "否",
                row.baidu_url or "",
                row.xunlei_url or "",
                row.quark_url or "",
            ]
        )
    widths = {"A": 28, "B": 12, "C": 10, "D": 56, "E": 56, "F": 56}
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


class CreateError(ValueError):
    pass


def _normalize_pan_url(raw: str, expected: str) -> str:
    cleaned = raw.strip()
    if not cleaned:
        return ""
    parsed = parse_share_link(cleaned)
    if parsed is None or parsed.provider != expected:
        raise CreateError(f"请填写有效的{_provider_label(expected)}链接")
    return cleaned


def _provider_label(provider: str) -> str:
    return {"baidu": "百度网盘", "quark": "夸克网盘", "xunlei": "迅雷网盘"}.get(
        provider, provider
    )


def create_item(
    session: Session,
    user_id: int,
    *,
    prefix: str,
    name: str,
    finished: bool = False,
    latest_episode: int | None = None,
    quark_url: str = "",
    baidu_url: str = "",
    xunlei_url: str = "",
) -> LibraryItem:
    from datetime import datetime, timezone

    cleaned_prefix = prefix.strip()
    if not cleaned_prefix.isdigit() or len(cleaned_prefix) > 16:
        raise CreateError("编号须为 1～16 位数字")
    title = name.strip()
    if not title:
        raise CreateError("请填写剧名")
    quark = _normalize_pan_url(quark_url, "quark")
    baidu = _normalize_pan_url(baidu_url, "baidu")
    xunlei = _normalize_pan_url(xunlei_url, "xunlei")
    if not (quark or baidu or xunlei):
        raise CreateError("至少填写一条网盘链接")
    exists = session.scalar(
        select(LibraryItem).where(
            LibraryItem.user_id == user_id, LibraryItem.prefix == cleaned_prefix
        )
    )
    if exists is not None:
        raise CreateError("编号已存在")
    now = datetime.now(timezone.utc)
    item = LibraryItem(
        user_id=user_id,
        prefix=cleaned_prefix,
        name=title,
        finished=bool(finished),
        latest_episode=latest_episode,
        quark_url=quark,
        baidu_url=baidu,
        xunlei_url=xunlei,
        created_at=now,
        updated_at=now,
    )
    session.add(item)
    session.flush()
    return item


def parse_folder_label(label: str) -> tuple[str, str, bool, int | None] | None:
    """Parse `009 朝朝入梦#59` / `010 朝云潜行#完结` / `020 …#完结#59`.

    Fullwidth `｜` is still accepted so folders renamed before the switch keep syncing.
    """
    parts = split_prefixed_name(label)
    if parts is None:
        return None
    prefix, rest = parts
    finished = False
    latest: int | None = None
    chunks = [chunk.strip() for chunk in re.split(r"[#｜]", rest) if chunk.strip()]
    if not chunks:
        return prefix, "", False, None
    title = chunks[0]
    for chunk in chunks[1:]:
        if chunk == "完结":
            finished = True
            continue
        if chunk.isdigit():
            latest = int(chunk)
            continue
        if "完结" in chunk:
            finished = True
            digits = "".join(ch for ch in chunk if ch.isdigit())
            if digits:
                latest = int(digits)
    return prefix, title, finished, latest


def apply_episode_from_folder_name(
    session: Session, user_id: int, folder_name: str
) -> bool:
    """Update library episode/finished from a folder name when they differ.

    Returns True when a matching library row was updated.
    """
    parsed = parse_folder_label(folder_name)
    if parsed is None:
        return False
    prefix, _title, finished, latest = parsed
    item = session.scalars(
        select(LibraryItem).where(
            LibraryItem.user_id == user_id, LibraryItem.prefix == prefix
        )
    ).first()
    if item is None and prefix.isdigit():
        key = int(prefix)
        item = next(
            (
                row
                for row in session.scalars(
                    select(LibraryItem).where(LibraryItem.user_id == user_id)
                ).all()
                if row.prefix.isdigit() and int(row.prefix) == key
            ),
            None,
        )
    if item is None:
        return False
    if bool(item.finished) == bool(finished) and item.latest_episode == latest:
        return False
    if item.latest_episode != latest:
        item.previous_episode = item.latest_episode
    item.finished = bool(finished)
    item.latest_episode = latest
    item.updated_at = datetime.now(timezone.utc)
    return True


def import_rows(session: Session, user_id: int, rows: list[ImportRow]) -> ImportResult:
    from datetime import datetime, timezone

    existing = {
        item.prefix: item
        for item in session.scalars(
            select(LibraryItem).where(LibraryItem.user_id == user_id)
        )
    }
    created: set[str] = set()
    updated: set[str] = set()
    skipped = 0
    now = datetime.now(timezone.utc)
    for row in rows:
        parts = split_prefixed_name(row.name)
        link = compose_link(row.url, row.password) if parts is not None else None
        parsed = parse_share_link(row.url.strip()) if link is not None else None
        if (
            parts is None
            or link is None
            or parsed is None
            or parsed.provider not in _FIELDS
        ):
            skipped += 1
            continue
        prefix, title = parts
        field = _FIELDS[parsed.provider]
        item = existing.get(prefix)
        if item is None:
            item = LibraryItem(
                user_id=user_id,
                prefix=prefix,
                name=title,
                xunlei_url="",
                quark_url="",
                baidu_url="",
                created_at=now,
                updated_at=now,
            )
            setattr(item, field, link)
            existing[prefix] = item
            created.add(prefix)
            session.add(item)
            continue
        changed = False
        if not item.name and title:
            item.name = title
            changed = True
        if getattr(item, field) != link:
            setattr(item, field, link)
            changed = True
        if changed and prefix not in created:
            item.updated_at = now
            updated.add(prefix)
    return ImportResult(created=len(created), updated=len(updated), skipped=skipped)
