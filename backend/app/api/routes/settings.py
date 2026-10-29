import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.crud.accounts import get_for_user
from app.models import ShareSetting, User
from app.schemas import SharePasswordsIn, SharePasswordsOut
from app.schemas.library_sync import (
    LibrarySyncSourceIn,
    LibrarySyncSourceOut,
    LibrarySyncSourcesIn,
)
from app.schemas.linked_rename import (
    LinkedRenameConfigIn,
    LinkedRenameConfigOut,
    LinkedRenameMemberIn,
    LinkedRenameMemberOut,
)
from app.services.library_sync import (
    SyncSourceDraft,
    list_sync_sources,
    replace_sync_sources,
)
from app.services.linked_rename import MemberDraft, list_members, replace_members
from app.services.transfers import normalize_directory

router = APIRouter()
_CODE = re.compile(r"^[0-9A-Za-z]{4}$")


def clean_code(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    if _CODE.fullmatch(cleaned) is None:
        raise HTTPException(status_code=422, detail="提取码需要 4 位字母或数字")
    return cleaned


def _source_out(row) -> LibrarySyncSourceOut:
    return LibrarySyncSourceOut(
        id=row.id,
        account_id=row.account_id,
        directory=row.directory,
        label=row.label,
        sort_order=row.sort_order,
    )


def _validate_sources(
    session: Session, user: User, sources: list[LibrarySyncSourceIn]
) -> list[SyncSourceDraft]:
    drafts: list[SyncSourceDraft] = []
    for index, source in enumerate(sources):
        account = get_for_user(session, user.id, source.account_id)
        if account is None:
            raise HTTPException(
                status_code=422, detail=f"第 {index + 1} 条同步目录的账号不存在"
            )
        if account.provider not in {"baidu", "quark", "xunlei"}:
            raise HTTPException(
                status_code=422, detail=f"第 {index + 1} 条同步目录的账号暂未开放"
            )
        try:
            directory = normalize_directory(source.directory)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"第 {index + 1} 条同步目录无效"
            ) from exc
        drafts.append(
            SyncSourceDraft(
                account_id=source.account_id,
                directory=directory,
                label=source.label,
                sort_order=source.sort_order if source.sort_order else index,
            )
        )
    return drafts


@router.get("/api/settings/share-passwords", response_model=SharePasswordsOut)
def read_share_passwords(
    user: User = Depends(get_current_user), session: Session = Depends(get_db)
):
    row = session.get(ShareSetting, user.id)
    if row is None:
        return SharePasswordsOut()
    return SharePasswordsOut(
        baidu_password=row.baidu_password,
        quark_password=row.quark_password,
        xunlei_password=row.xunlei_password,
    )


@router.put("/api/settings/share-passwords", response_model=SharePasswordsOut)
def save_share_passwords(
    body: SharePasswordsIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    baidu = clean_code(body.baidu_password)
    quark = clean_code(body.quark_password)
    xunlei = clean_code(body.xunlei_password)
    row = session.get(ShareSetting, user.id)
    if row is None:
        row = ShareSetting(
            user_id=user.id,
            baidu_password=baidu,
            quark_password=quark,
            xunlei_password=xunlei,
        )
        session.add(row)
    else:
        row.baidu_password = baidu
        row.quark_password = quark
        row.xunlei_password = xunlei
    session.commit()
    return SharePasswordsOut(
        baidu_password=baidu, quark_password=quark, xunlei_password=xunlei
    )


@router.get(
    "/api/settings/library-sync-sources", response_model=list[LibrarySyncSourceOut]
)
def read_library_sync_sources(
    user: User = Depends(get_current_user), session: Session = Depends(get_db)
):
    return [_source_out(row) for row in list_sync_sources(session, user.id)]


@router.put(
    "/api/settings/library-sync-sources", response_model=list[LibrarySyncSourceOut]
)
def save_library_sync_sources(
    body: LibrarySyncSourcesIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    drafts = _validate_sources(session, user, body.sources)
    rows = replace_sync_sources(session, user.id, drafts)
    session.commit()
    return [_source_out(row) for row in rows]


def _member_out(row) -> LinkedRenameMemberOut:
    return LinkedRenameMemberOut(
        id=row.id,
        account_id=row.account_id,
        directory=row.directory,
        label=row.label,
        is_primary=bool(row.is_primary),
        sort_order=row.sort_order,
    )


def _validate_linked_members(
    session: Session, user: User, members: list[LinkedRenameMemberIn]
) -> list[MemberDraft]:
    if not members:
        return []
    primaries = [row for row in members if row.is_primary]
    if len(primaries) != 1:
        raise HTTPException(status_code=422, detail="需要且只能设置一个主目录")
    if len(members) < 2:
        raise HTTPException(status_code=422, detail="请至少再添加一个关联目录")
    drafts: list[MemberDraft] = []
    for index, member in enumerate(members):
        account = get_for_user(session, user.id, member.account_id)
        if account is None:
            raise HTTPException(
                status_code=422, detail=f"第 {index + 1} 条关联目录的账号不存在"
            )
        if account.provider not in {"baidu", "quark", "xunlei"}:
            raise HTTPException(
                status_code=422, detail=f"第 {index + 1} 条关联目录的账号暂未开放"
            )
        try:
            directory = normalize_directory(member.directory)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"第 {index + 1} 条关联目录无效"
            ) from exc
        drafts.append(
            MemberDraft(
                account_id=member.account_id,
                directory=directory,
                label=member.label,
                is_primary=bool(member.is_primary),
                sort_order=member.sort_order if member.sort_order else index,
            )
        )
    return drafts


@router.get("/api/settings/linked-rename", response_model=LinkedRenameConfigOut)
def read_linked_rename(
    user: User = Depends(get_current_user), session: Session = Depends(get_db)
):
    return LinkedRenameConfigOut(
        members=[_member_out(row) for row in list_members(session, user.id)]
    )


@router.put("/api/settings/linked-rename", response_model=LinkedRenameConfigOut)
def save_linked_rename(
    body: LinkedRenameConfigIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    drafts = _validate_linked_members(session, user, body.members)
    rows = replace_members(session, user.id, drafts)
    session.commit()
    return LinkedRenameConfigOut(members=[_member_out(row) for row in rows])
