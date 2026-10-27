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


def _sync_order(db, alarm_id: int, note: str | None = None) -> None:
    """告警关闭时把未销号的关联工单一起关掉，避免"告警关了工单还挂着"。"""
    from datetime import datetime

    from app.models.inspection import WorkOrder

    try:
        o = (db.query(WorkOrder)
             .filter(WorkOrder.source == "alarm", WorkOrder.source_id == alarm_id,
                     WorkOrder.status != "closed")
             .first())
        if o is not None:
            o.status = "closed"
            o.closed_at = datetime.now()
            o.resolution = (f"{o.resolution}｜" if o.resolution else "") + "来源告警已关闭（联动）"
            o.description = (o.description or "") + (f"｜告警结论：{note}" if note else "")
            # 联动关单也要留痕：等保查"工单为什么自己关了"时要能答
            from app.services.messages import audit as _audit

            _audit(db=db, action="work_order.auto_close", target=o.code or f"#{o.id}",
                   user=None, detail={"by": "alarm.close", "alarm_id": alarm_id, "note": note})
    except Exception:  # noqa: BLE001
        pass


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


@router.get("/kpi")
def alarm_kpi(
    hours: int = Query(24, ge=1, le=24 * 30),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """告警治理 KPI（ISA-18.2 口径）：频次、洪泛、待处理、分级分布。"""
    from datetime import datetime, timedelta

    from sqlalchemy import func, select

    from app.models.alarm import AlarmRecord

    end = datetime.now()
    start = end - timedelta(hours=hours)
    rows = db.scalars(select(AlarmRecord)
                      .where(AlarmRecord.started_at >= start)).all()

    total = len(rows)
    by_priority: dict[str, int] = {}
    by_level: dict[str, int] = {}
    by_metric: dict[str, int] = {}
    for a in rows:
        p = getattr(a, "priority", None) or "P4"
        by_priority[p] = by_priority.get(p, 0) + 1
        by_level[a.level] = by_level.get(a.level, 0) + 1
        by_metric[a.metric] = by_metric.get(a.metric, 0) + 1

    # 10 分钟窗口最大条数 → 判断洪泛（ISA-18.2 建议 <10 条/10 分钟）
    buckets: dict[str, int] = {}
    for a in rows:
        if not a.started_at:
            continue
        key = a.started_at.strftime("%Y%m%d%H") + f"{a.started_at.minute // 10}"
        buckets[key] = buckets.get(key, 0) + 1
    peak_10min = max(buckets.values()) if buckets else 0
    flood_windows = sum(1 for v in buckets.values() if v >= 10)

    open_rows = db.scalar(select(func.count()).select_from(AlarmRecord)
                          .where(AlarmRecord.closed_at.is_(None),
                                 AlarmRecord.started_at >= start)) or 0
    unacked = db.scalar(select(func.count()).select_from(AlarmRecord)
                        .where(AlarmRecord.acked_at.is_(None),
                               AlarmRecord.started_at >= start)) or 0
    shelved = db.scalar(select(func.count()).select_from(AlarmRecord)
                        .where(AlarmRecord.shelved_until.isnot(None),
                               AlarmRecord.shelved_until > datetime.now())) or 0

    per_hour = round(total / hours, 1) if hours else 0
    return {
        "hours": hours,
        "total": total,
        "per_hour": per_hour,
        "peak_10min": peak_10min,
        "flood_windows": flood_windows,
        "flood_ratio": round(flood_windows / len(buckets) * 100, 1) if buckets else 0,
        "open": open_rows,
        "unacked": unacked,
        "shelved": shelved,
        "by_priority": by_priority,
        "by_level": by_level,
        "top_metrics": sorted(by_metric.items(), key=lambda x: -x[1])[:5],
        "targets": {"per_hour": 6, "peak_10min": 10, "flood_ratio": 1},
    }


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
    _sync_order(db, alarm_id, note=body.resolution)
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
