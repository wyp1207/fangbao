from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models.user import User
from app.services.messages import audit_list

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("")
def list_audit_logs(
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    action: str | None = Query(None, description="按动作过滤，如 alarm.ack"),
    username: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> dict:
    """操作审计：谁在什么时候做了什么。只有管理员能看。"""
    return audit_list(db, limit=limit, offset=offset, action=action, username=username)
