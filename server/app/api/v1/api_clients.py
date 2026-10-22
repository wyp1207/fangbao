"""机器身份：API Key 创建/吊销。

机器人回传、算法盒推送、厂内系统对接都走这里，不用人账号。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_csrf, require_roles
from app.core.errors import NotFound
from app.db.session import get_db
from app.models.ai import ApiClient, new_key
from app.models.user import User
from app.services.messages import audit

router = APIRouter(prefix="/api-clients", tags=["api-clients"])

VALID_SCOPES = ("task:ingest", "ai:write", "sensor:write", "read:alarms")


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    scopes: list[str] = Field(default_factory=lambda: ["task:ingest"])


def _out(c: ApiClient) -> dict:
    return {
        "id": c.id, "name": c.name, "prefix": c.prefix,
        "scopes": [s for s in (c.scopes or "").split(",") if s],
        "enabled": c.enabled,
        "created_at": c.created_at.isoformat(timespec="minutes") if c.created_at else None,
        "last_used_at": c.last_used_at.isoformat(timespec="minutes") if c.last_used_at else None,
    }


@router.get("")
def list_clients(db: Session = Depends(get_db),
                 _: User = Depends(require_roles("admin", "sysadmin"))) -> list[dict]:
    return [_out(c) for c in db.query(ApiClient).order_by(ApiClient.id.desc()).all()]


@router.post("", dependencies=[Depends(require_csrf)])
def create_client(
    body: ClientIn, db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "sysadmin")),
) -> dict:
    bad = [s for s in body.scopes if s not in VALID_SCOPES]
    if bad:
        from app.core.errors import BadRequest
        raise BadRequest(f"未知权限 {bad}，可用：{', '.join(VALID_SCOPES)}", code="BAD_SCOPE")

    raw, hashed, prefix = new_key()
    c = ApiClient(name=body.name.strip()[:64], key_hash=hashed, prefix=prefix,
                  scopes=",".join(body.scopes))
    db.add(c)
    db.commit()
    db.refresh(c)
    audit(db=db, action="api_client.create", target=c.name, user=me,
          detail={"scopes": body.scopes})
    # 明文只在这里返回一次
    return {**_out(c), "key": raw}


@router.delete("/{client_id}", dependencies=[Depends(require_csrf)])
def revoke_client(
    client_id: int, db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "sysadmin")),
) -> dict:
    c = db.get(ApiClient, client_id)
    if not c:
        raise NotFound("密钥不存在")
    c.enabled = False
    db.commit()
    audit(db=db, action="api_client.revoke", target=c.name, user=me)
    return {"ok": True}
