from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db

from app.api.deps import get_alarms, get_current_user, require_csrf, require_roles
from app.core.errors import BadRequest, NotFound
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


@router.post("/{alarm_id}/shelve", dependencies=[Depends(require_csrf)])
def shelve_alarm(
    alarm_id: int,
    body: dict,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator", "safety")),
) -> dict:
    """搁置告警（ISA-18.2）：检修/标定时临时屏蔽，必须填原因和时长。"""
    from datetime import datetime, timedelta

    from app.models.alarm import AlarmRecord

    minutes = int(body.get("minutes") or 0)
    reason = str(body.get("reason") or "").strip()
    if minutes <= 0 or minutes > 7 * 24 * 60:
        raise BadRequest("搁置时长需在 1 分钟到 7 天之间", code="BAD_DURATION")
    if not reason:
        raise BadRequest("必须填写搁置原因（审计要留痕）", code="REASON_REQUIRED")

    a = db.get(AlarmRecord, alarm_id)
    if a is None:
        raise NotFound("告警不存在")
    a.shelved_until = datetime.now() + timedelta(minutes=minutes)
    a.shelve_reason = reason[:200]
    db.commit()
    audit(db=db, action="alarm.shelve", target=f"#{alarm_id}", user=me,
          detail={"minutes": minutes, "reason": reason})
    return {"ok": True, "shelved_until": a.shelved_until.isoformat(timespec="minutes")}


@router.delete("/{alarm_id}/shelve", dependencies=[Depends(require_csrf)])
def unshelve_alarm(
    alarm_id: int, db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator", "safety")),
) -> dict:
    from app.models.alarm import AlarmRecord

    a = db.get(AlarmRecord, alarm_id)
    if a is None:
        raise NotFound("告警不存在")
    a.shelved_until = None
    a.shelve_reason = None
    db.commit()
    audit(db=db, action="alarm.unshelve", target=f"#{alarm_id}", user=me)
    return {"ok": True}


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


class _HandleIn(BaseModel):
    note: str = Field(min_length=1, max_length=500)


class _CloseIn(BaseModel):
    resolution: str = Field(default="handled")   # handled/defect/misreport/ignored
    note: str = Field(default="", max_length=500)


@router.post("/{alarm_id}/handle", dependencies=[Depends(require_csrf)])
def handle_alarm(
    alarm_id: int,
    body: _HandleIn,
    request: Request,
    db: Session = Depends(get_db),
    store=Depends(get_alarms),
    user: User = Depends(require_roles("admin", "operator")),
) -> dict:
    """处置：写清做了什么，区别于"点一下确认"。"""
    alarm = store.handle(alarm_id, who=user.username, note=body.note)
    if alarm is None:
        raise NotFound(f"告警 {alarm_id} 不存在")
    from app.services.messages import store as msg_store

    msg_store.add("info", "alarm", f"告警已处置：{alarm['message']}",
                  f"{user.username}：{body.note}", {"to": "alarms"})
    audit(db=db, action="alarm.handle", target=f"alarm:{alarm_id}", user=user,
          client_ip=request.client.host if request.client else None,
          detail={"note": body.note}, summary=body.note)
    return alarm


@router.post("/{alarm_id}/close", dependencies=[Depends(require_csrf)])
def close_alarm(
    alarm_id: int,
    body: _CloseIn,
    request: Request,
    db: Session = Depends(get_db),
    store=Depends(get_alarms),
    user: User = Depends(require_roles("admin", "operator")),
) -> dict:
    """关闭：给出结论（已处理/设备缺陷/误报/忽略）。"""
    allowed = {"handled", "defect", "misreport", "ignored"}
    if body.resolution not in allowed:
        raise BadRequest(f"结论只能是 {', '.join(sorted(allowed))}", code="BAD_RESOLUTION")
    alarm = store.close(alarm_id, who=user.username, resolution=body.resolution, note=body.note)
    if alarm is None:
        raise NotFound(f"告警 {alarm_id} 不存在")
    from app.services.messages import store as msg_store

    msg_store.add("info", "alarm", f"告警已关闭：{alarm['message']}",
                  f"{user.username} · {body.resolution}", {"to": "alarms"})
    audit(db=db, action="alarm.close", target=f"alarm:{alarm_id}", user=user,
          client_ip=request.client.host if request.client else None,
          detail={"resolution": body.resolution, "note": body.note}, summary=body.resolution)
    return alarm


@router.get("/stats")
def alarm_stats(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    """近 N 日告警趋势：按天分级别计数 + 未确认/总数。"""
    from datetime import date, datetime, timedelta

    from sqlalchemy import func, select

    from app.models.alarm import AlarmRecord

    start = datetime.combine(date.today() - timedelta(days=days - 1), datetime.min.time())
    rows = db.execute(
        select(AlarmRecord.started_at, AlarmRecord.level, AlarmRecord.acked_at)
        .where(AlarmRecord.started_at >= start)
    ).all()

    buckets: dict[str, dict[str, int]] = {}
    for i in range(days):
        d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        buckets[d] = {"warn": 0, "critical": 0}

    unacked = acked = 0
    for started, level, acked_at in rows:
        if started is None:
            continue
        key = started.date().isoformat()
        if key in buckets and level in buckets[key]:
            buckets[key][level] += 1
        if acked_at is None:
            unacked += 1
        else:
            acked += 1

    series = [{"date": d, "warn": v["warn"], "critical": v["critical"],
               "total": v["warn"] + v["critical"]} for d, v in buckets.items()]
    return {"days": days, "series": series, "total": len(rows),
            "unacked": unacked, "acked": acked,
            "peak": max((s["total"] for s in series), default=0)}


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
