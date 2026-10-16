from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models import User
from app.models.library import LibraryItem
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
from app.services.library import CreateError, ImportRow, create_item, import_rows, list_items
from app.services.library_links import check_library_links

router = APIRouter()


def _out(item: LibraryItem) -> LibraryItemOut:
    return LibraryItemOut(
        id=item.id,
        prefix=item.prefix,
        name=item.name,
        xunlei_url=item.xunlei_url,
        quark_url=item.quark_url,
        baidu_url=item.baidu_url,
    )


@router.get("/api/library", response_model=list[LibraryItemOut])
def read_library(user: User = Depends(get_current_user), session: Session = Depends(get_db)):
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
            quark_url=body.quark_url,
            baidu_url=body.baidu_url,
            xunlei_url=body.xunlei_url,
        )
    except CreateError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return _out(item)


@router.post("/api/library/check", response_model=LibraryCheckOut)
def check_library(user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    with httpx.Client(timeout=12, follow_redirects=False) as client:
        result = check_library_links(list_items(session, user.id), client)
    return LibraryCheckOut(
        checked=result.checked,
        unknown=result.unknown,
        invalid=[
            LibraryCheckHit(id=hit.id, prefix=hit.prefix, name=hit.name, provider=hit.provider, reason=hit.reason)
            for hit in result.invalid
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
        [ImportRow(name=row.name, url=row.url, password=row.password) for row in body.rows],
    )
    session.commit()
    return LibraryImportOut(
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        items=[_out(item) for item in list_items(session, user.id)],
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
