import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models import ShareSetting, User
from app.schemas import SharePasswordsIn, SharePasswordsOut

router = APIRouter()
_CODE = re.compile(r"^[0-9A-Za-z]{4}$")


def clean_code(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    if _CODE.fullmatch(cleaned) is None:
        raise HTTPException(status_code=422, detail="提取码需要 4 位字母或数字")
    return cleaned


@router.get("/api/settings/share-passwords", response_model=SharePasswordsOut)
def read_share_passwords(user: User = Depends(get_current_user), session: Session = Depends(get_db)):
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
        row = ShareSetting(user_id=user.id, baidu_password=baidu, quark_password=quark, xunlei_password=xunlei)
        session.add(row)
    else:
        row.baidu_password = baidu
        row.quark_password = quark
        row.xunlei_password = xunlei
    session.commit()
    return SharePasswordsOut(baidu_password=baidu, quark_password=quark, xunlei_password=xunlei)
