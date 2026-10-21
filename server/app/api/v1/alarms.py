from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.db.session import get_db

from app.api.deps import get_alarms, get_current_user, require_csrf, require_roles
from app.core.errors import NotFound
from app.models.user import User
from app.services.messages import audit

router = APIRouter(prefix="/alarms", tags=["alarms"])


@router.get("")
def list_alarms(
    status: str | None = Query(None, description="unacked | acked"),
    level: str | None = Query(None, description="warn | critical"),
    metric: str | None = Query(None),
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
    q: str | None = Query(None, description="内容关键词"),
    limit: int = Query(200, le=500),
    offset: int = Query(0, ge=0),
    store=Depends(get_alarms),
    _user: User = Depends(get_current_user),
) -> dict:
    """告警列表（数据库查询，重启不丢）。

    兼容老调用：不带任何筛选、只传 active=true 时仍返回数组形状的 items。
    """
    res = store.query(limit=limit, offset=offset, status=status, level=level,
                      metric=metric, date_from=date_from, date_to=date_to, q=q)
    return res


@router.get("/latest")
def latest_alarms(
    limit: int = Query(50, le=200),
    active: bool = Query(False, description="只看未确认"),
    store=Depends(get_alarms),
    _user: User = Depends(get_current_user),
) -> dict:
    """驾驶舱用：最近的告警（数组形状，前端直接渲染）。"""
    res = store.query(limit=limit, status="unacked" if active else None)
    return res


@router.post("/{alarm_id}/ack", dependencies=[Depends(require_csrf)])
def ack_alarm(
    alarm_id: int,
    request: Request,
    db: Session = Depends(get_db),
    store=Depends(get_alarms),
    user: User = Depends(require_roles("admin", "operator")),
) -> dict:
    alarm = store.ack(alarm_id, who=user.username)
    if alarm is None:
        raise NotFound(f"告警 {alarm_id} 不存在")

    from app.services.messages import store as msg_store

    msg_store.add("info", "alarm", f"告警已确认：{alarm['message']}",
                  f"确认人 {user.username}",
                  {"to": "alarms", "query": {"status": "acked"}})
    audit(db=db, action="alarm.ack", target=f"alarm:{alarm_id}",
          user=user, client_ip=request.client.host if request.client else None,
          summary=alarm["message"])
    return alarm
