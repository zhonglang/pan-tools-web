from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_cookie
from app.core.deps import get_current_user, get_db
from app.models import User
from app.models.library import LibraryItem
from app.pans import adapter_for
from app.pans.errors import LoginRejected, PathNotFound
from app.schemas import OkOut
from app.schemas.library import (
    LibraryCheckHit,
    LibraryCheckOut,
    LibraryCreateIn,
    LibraryImportIn,
    LibraryImportOut,
    LibraryItemIn,
    LibraryItemOut,
)
from app.schemas.library_sync import LibraryEpisodeSyncHit, LibraryEpisodeSyncOut
from app.services.library import (
    CreateError,
    ImportRow,
    create_item,
    import_rows,
    library_xlsx,
    list_items,
)
from app.services.library_links import check_library_links
from app.services.library_sync import sync_episodes

router = APIRouter()


def _out(item: LibraryItem) -> LibraryItemOut:
    return LibraryItemOut(
        id=item.id,
        prefix=item.prefix,
        name=item.name,
        finished=bool(item.finished),
        latest_episode=item.latest_episode,
        previous_episode=item.previous_episode,
        xunlei_url=item.xunlei_url,
        quark_url=item.quark_url,
        baidu_url=item.baidu_url,
        updated_at=item.updated_at.isoformat() if item.updated_at else None,
    )


@router.get("/api/library", response_model=list[LibraryItemOut])
def read_library(
    user: User = Depends(get_current_user), session: Session = Depends(get_db)
):
    return [_out(item) for item in list_items(session, user.id)]


@router.post("/api/library", response_model=LibraryItemOut, status_code=201)
def create_library_item(
    body: LibraryCreateIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    try:
        item = create_item(
            session,
            user.id,
            prefix=body.prefix,
            name=body.name,
            finished=body.finished,
            latest_episode=body.latest_episode,
            quark_url=body.quark_url,
            baidu_url=body.baidu_url,
            xunlei_url=body.xunlei_url,
        )
    except CreateError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return _out(item)


@router.post("/api/library/check", response_model=LibraryCheckOut)
def check_library(
    user: User = Depends(get_current_user), session: Session = Depends(get_db)
):
    with httpx.Client(timeout=12, follow_redirects=False) as client:
        result = check_library_links(list_items(session, user.id), client)
    return LibraryCheckOut(
        checked=result.checked,
        unknown=result.unknown,
        invalid=[
            LibraryCheckHit(
                id=hit.id,
                prefix=hit.prefix,
                name=hit.name,
                provider=hit.provider,
                reason=hit.reason,
            )
            for hit in result.invalid
        ],
    )


@router.post("/api/library/sync-episodes", response_model=LibraryEpisodeSyncOut)
def sync_library_episodes(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    from app.api.routes.transfers import (
        owned_drive,
        pan_client,
        persist_warmed,
        relogin,
    )

    def list_folders(account_id: int, directory: str) -> list[str]:
        account = owned_drive(session, user, account_id, allow_expired=True)
        cookie = decrypt_cookie(
            account.cookie_ciphertext, get_settings().cookie_fernet_key
        )
        adapter = adapter_for(account.provider, pan_client(request))
        try:
            entries = adapter.list_dir(cookie, directory)
            persist_warmed(session, account, cookie, adapter)
            if account.status != "valid":
                account.status = "valid"
                account.updated_at = datetime.now(timezone.utc)
                session.commit()
        except LoginRejected as exc:
            account.status = "expired"
            account.updated_at = datetime.now(timezone.utc)
            session.commit()
            raise HTTPException(
                status_code=422, detail=relogin(account.provider)
            ) from exc
        except PathNotFound as exc:
            label = account.nickname or account.provider
            raise HTTPException(
                status_code=422, detail=f"{label} 的同步目录不存在"
            ) from exc
        return [entry.name for entry in entries if entry.is_dir]

    try:
        result = sync_episodes(session, user.id, list_folders=list_folders)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    return LibraryEpisodeSyncOut(
        updated=result.updated,
        unchanged=result.unchanged,
        unmatched=result.unmatched,
        items=[
            LibraryEpisodeSyncHit(
                id=hit.id,
                prefix=hit.prefix,
                name=hit.name,
                finished=hit.finished,
                latest_episode=hit.latest_episode,
                changed=hit.changed,
            )
            for hit in result.items
        ],
    )


@router.post("/api/library/import", response_model=LibraryImportOut)
def import_library(
    body: LibraryImportIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    result = import_rows(
        session,
        user.id,
        [
            ImportRow(name=row.name, url=row.url, password=row.password)
            for row in body.rows
        ],
    )
    session.commit()
    return LibraryImportOut(
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        items=[_out(item) for item in list_items(session, user.id)],
    )


@router.get("/api/library/export")
def export_library(
    user: User = Depends(get_current_user), session: Session = Depends(get_db)
):
    return Response(
        content=library_xlsx(list_items(session, user.id)),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="library.xlsx"'},
    )


@router.patch("/api/library/{item_id}", response_model=LibraryItemOut)
def update_library_item(
    item_id: int,
    body: LibraryItemIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    item = session.get(LibraryItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="没有找到这部资源")
    item.name = body.name.strip()
    item.finished = bool(body.finished)
    if body.latest_episode != item.latest_episode:
        item.previous_episode = item.latest_episode
        item.latest_episode = body.latest_episode
    item.xunlei_url = body.xunlei_url.strip()
    item.quark_url = body.quark_url.strip()
    item.baidu_url = body.baidu_url.strip()
    item.updated_at = datetime.now(timezone.utc)
    session.commit()
    return _out(item)


@router.delete("/api/library/{item_id}", response_model=OkOut)
def delete_library_item(
    item_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    item = session.get(LibraryItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="没有找到这部资源")
    session.delete(item)
    session.commit()
    return OkOut(ok=True)
