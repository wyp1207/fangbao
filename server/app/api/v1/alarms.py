from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_alarms, require_csrf, require_roles
from app.api.deps import get_current_user
from app.core.errors import NotFound
from app.models.user import User

router = APIRouter(prefix="/alarms", tags=["alarms"])


@router.get("")
def list_alarms(active: bool = Query(False, description="只看未确认"),
                store=Depends(get_alarms),
                _user: User = Depends(get_current_user)) -> list[dict]:
    return store.list(active_only=active)


@router.post("/{alarm_id}/ack", dependencies=[Depends(require_csrf)])
def ack_alarm(alarm_id: int, store=Depends(get_alarms),
              user: User = Depends(require_roles("admin", "operator"))) -> dict:
    alarm = store.ack(alarm_id, who=user.username)
    from app.services.messages import store as msg_store
    msg_store.add("info", "alarm", f"告警已确认：{alarm.message}", f"确认人 {user.username}",
                  {"to": "alarms", "query": {"status": "acked"}})
    if alarm is None:
        raise NotFound(f"告警 {alarm_id} 不存在")
    return alarm
