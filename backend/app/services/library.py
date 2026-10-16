import re
from dataclasses import dataclass

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
    rows = session.scalars(select(LibraryItem).where(LibraryItem.user_id == user_id)).all()
    return sorted(rows, key=lambda item: (int(item.prefix), item.prefix))


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
    return {"baidu": "百度网盘", "quark": "夸克网盘", "xunlei": "迅雷网盘"}.get(provider, provider)


def create_item(
    session: Session,
    user_id: int,
    *,
    prefix: str,
    name: str,
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
        select(LibraryItem).where(LibraryItem.user_id == user_id, LibraryItem.prefix == cleaned_prefix)
    )
    if exists is not None:
        raise CreateError("编号已存在")
    now = datetime.now(timezone.utc)
    item = LibraryItem(
        user_id=user_id,
        prefix=cleaned_prefix,
        name=title,
        quark_url=quark,
        baidu_url=baidu,
        xunlei_url=xunlei,
        created_at=now,
        updated_at=now,
    )
    session.add(item)
    session.flush()
    return item


def import_rows(session: Session, user_id: int, rows: list[ImportRow]) -> ImportResult:
    from datetime import datetime, timezone

    existing = {item.prefix: item for item in session.scalars(select(LibraryItem).where(LibraryItem.user_id == user_id))}
    created: set[str] = set()
    updated: set[str] = set()
    skipped = 0
    now = datetime.now(timezone.utc)
    for row in rows:
        parts = split_prefixed_name(row.name)
        link = compose_link(row.url, row.password) if parts is not None else None
        parsed = parse_share_link(row.url.strip()) if link is not None else None
        if parts is None or link is None or parsed is None or parsed.provider not in _FIELDS:
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
