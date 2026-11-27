"""场站（site）台账：列表 + 创建 + 修改。

P0 只做后端：前端先用通用列表/表单接，不改现有页面。
关键约束：
- GET 需要登录，但**不会**为了"让页面好看"自动造默认场站——空就是空；
- code 唯一且稳定（中文名用短 hash），改 name 不改 code，避免日志/脚本对不上；
- 停用用 status=0，不物理删除（设备/地图/历史任务都还挂在上面）。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_csrf, require_roles
from app.core.errors import BadRequest, NotFound, PlatformError
from app.db.session import get_db
from app.models.site import Site
from app.models.user import User
from app.services.messages import audit
from app.services.sites import unique_code

router = APIRouter(prefix="/sites", tags=["sites"])


class SiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    code: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=200)
    status: int = 1


class SitePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    code: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=200)
    status: int | None = None


def _out(s: Site) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "code": s.code,
        "address": s.address,
        "status": int(s.status or 0),
        "created_at": s.created_at.isoformat(timespec="seconds") if s.created_at else None,
    }


@router.get("")
def list_sites(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[dict]:
    """场站列表：只读，不自动补数据。"""
    rows = db.query(Site).order_by(Site.id).all()
    return [_out(s) for s in rows]


@router.post("", dependencies=[Depends(require_csrf)])
def create_site(
    body: SiteIn,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "sysadmin")),
) -> dict:
    name = body.name.strip()
    if not name:
        raise BadRequest("场站名不能为空", code="EMPTY_NAME")
    if db.query(Site).filter(Site.name == name).first():
        raise PlatformError(f"场站「{name}」已存在", code="SITE_EXISTS", status_code=409)
    site = Site(
        name=name,
        code=unique_code(db, name, body.code),
        address=(body.address or "").strip() or None,
        status=1 if body.status else 0,
        created_at=datetime.now(),
    )
    db.add(site)
    db.commit()
    db.refresh(site)
    audit(db=db, action="site.create", target=site.name, user=me,
          detail={"code": site.code, "status": site.status})
    return _out(site)


@router.patch("/{site_id}", dependencies=[Depends(require_csrf)])
def update_site(
    site_id: int,
    body: SitePatch,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "sysadmin")),
) -> dict:
    site = db.get(Site, site_id)
    if site is None:
        raise NotFound("场站不存在")

    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise BadRequest("场站名不能为空", code="EMPTY_NAME")
        dup = db.query(Site).filter(Site.name == name, Site.id != site_id).first()
        if dup:
            raise PlatformError(f"场站「{name}」已存在", code="SITE_EXISTS", status_code=409)
        site.name = name
    if "code" in data and data["code"]:
        code = data["code"].strip()
        dup = db.query(Site).filter(Site.code == code, Site.id != site_id).first()
        if dup:
            raise PlatformError(f"场站编码 {code} 已存在", code="SITE_CODE_TAKEN",
                                status_code=409)
        site.code = code
    if "address" in data:
        site.address = (data["address"] or "").strip() or None
    if "status" in data and data["status"] is not None:
        site.status = 1 if data["status"] else 0

    db.commit()
    db.refresh(site)
    audit(db=db, action="site.update", target=site.name, user=me, detail=data)
    return _out(site)
