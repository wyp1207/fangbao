"""环境传感器：台账 + 读数 + 超限告警。

设计取舍：
- 阈值 NULL = 未标定 → 不产生告警，页面显示「未标定」。不拿 0 冒充阈值。
- 读数可按时间范围查，返回等间隔降采样序列（图表用），原始点不删。
- 告警走同一套 AlarmStore（metric=env_<kind>），确认/审计/消息全都复用。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_alarms, get_current_user, require_csrf, require_roles
from app.core.errors import BadRequest, NotFound
from app.db.session import get_db
from app.models.sensor import Sensor, SensorReading
from app.models.user import User
from app.services.messages import audit

router = APIRouter(prefix="/sensors", tags=["sensors"])

KINDS: dict[str, dict[str, Any]] = {
    "gas": {"label": "可燃气体", "unit": "%LEL"},
    "smoke": {"label": "烟雾", "unit": "%obs"},
    "temperature": {"label": "温度", "unit": "℃"},
    "humidity": {"label": "湿度", "unit": "%RH"},
    "pm": {"label": "PM2.5", "unit": "μg/m³"},
    "noise": {"label": "噪声", "unit": "dB"},
    "o2": {"label": "氧气", "unit": "%VOL"},
    "h2s": {"label": "硫化氢", "unit": "ppm"},
    "co": {"label": "一氧化碳", "unit": "ppm"},
}


class SensorIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: str
    station: str = "默认场站"
    location: str | None = None
    serial: str | None = None
    warn_low: float | None = None
    warn_high: float | None = None
    crit_low: float | None = None
    crit_high: float | None = None
    note: str | None = None
    enabled: bool = True


class ReadingIn(BaseModel):
    value: float
    ts: datetime | None = None
    source: Literal["manual", "robot", "gateway"] = "manual"


def _out(s: Sensor, latest: SensorReading | None = None) -> dict:
    return {
        "id": s.id, "name": s.name, "kind": s.kind,
        "kind_label": KINDS.get(s.kind, {}).get("label", s.kind),
        "unit": s.unit or KINDS.get(s.kind, {}).get("unit", ""),
        "station": s.station, "location": s.location, "serial": s.serial,
        "warn_low": s.warn_low, "warn_high": s.warn_high,
        "crit_low": s.crit_low, "crit_high": s.crit_high,
        "enabled": s.enabled, "note": s.note,
        "calibrated": any(v is not None for v in (s.warn_low, s.warn_high, s.crit_low, s.crit_high)),
        "latest": None if latest is None else {
            "value": latest.value, "ts": latest.ts.isoformat(timespec="seconds"),
            "source": latest.source,
        },
    }


@router.get("/meta")
def sensor_meta(_: User = Depends(get_current_user)) -> dict:
    return {"kinds": [{"value": k, **v} for k, v in KINDS.items()]}


@router.get("")
def list_sensors(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    rows = db.query(Sensor).order_by(Sensor.id).all()
    latest: dict[int, SensorReading] = {}
    for r in db.query(SensorReading).order_by(SensorReading.ts.desc()).limit(500).all():
        latest.setdefault(r.sensor_id, r)
    return [_out(s, latest.get(s.id)) for s in rows]


@router.post("", dependencies=[Depends(require_csrf)])
def create_sensor(
    body: SensorIn,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    if body.kind not in KINDS:
        raise BadRequest(f"未知传感器类型 {body.kind}", code="BAD_KIND")
    if body.warn_high is not None and body.crit_high is not None and body.crit_high < body.warn_high:
        raise BadRequest("严重阈值应大于提醒阈值", code="BAD_THRESHOLD")
    s = Sensor(**body.model_dump(), unit=KINDS[body.kind]["unit"])
    db.add(s)
    db.commit()
    db.refresh(s)
    audit(db=db, action="sensor.create", target=s.name, user=me, detail=body.model_dump())
    return _out(s)


@router.patch("/{sensor_id}", dependencies=[Depends(require_csrf)])
def update_sensor(
    sensor_id: int,
    body: dict,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    s = db.get(Sensor, sensor_id)
    if not s:
        raise NotFound("传感器不存在")

    allowed = {"name", "station", "location", "serial", "warn_low", "warn_high",
               "crit_low", "crit_high", "note", "enabled"}

    # 把已经标定的阈值清空 = 让这个测点永久静默，属于高危动作
    threshold_keys = ("warn_low", "warn_high", "crit_low", "crit_high")
    if any(k in body for k in threshold_keys) and me.role not in ("admin", "safety"):
        raise BadRequest("修改阈值需要管理员或安全管理员", code="FORBIDDEN")
    if any(k in body for k in threshold_keys):
        before = any(getattr(s, k) is not None for k in threshold_keys)
        after = any((body.get(k, getattr(s, k)) is not None) for k in threshold_keys)
        if before and not after:
            if me.role not in ("admin", "safety"):
                raise BadRequest("清空阈值会让该测点停止告警，只有管理员可以操作",
                                 code="NEED_ADMIN")
            from app.services.messages import store as msg_store
            msg_store.add("danger", "system", f"传感器阈值被清空：{s.name}",
                          f"{me.username} 清空了全部阈值，该测点将不再告警",
                          {"to": "env-device"})
    for k, v in body.items():
        if k in allowed:
            setattr(s, k, v)
    db.commit()
    db.refresh(s)
    audit(db=db, action="sensor.update", target=s.name, user=me, detail=body)
    return _out(s)


@router.delete("/{sensor_id}", dependencies=[Depends(require_csrf)])
def delete_sensor(
    sensor_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin")),
) -> dict:
    s = db.get(Sensor, sensor_id)
    if not s:
        raise NotFound("传感器不存在")
    db.query(SensorReading).filter(SensorReading.sensor_id == sensor_id).delete()
    db.delete(s)
    db.commit()
    audit(db=db, action="sensor.delete", target=s.name, user=me)
    return {"ok": True}


@router.post("/{sensor_id}/readings", dependencies=[Depends(require_csrf)])
def add_reading(
    sensor_id: int,
    body: ReadingIn,
    db: Session = Depends(get_db),
    store=Depends(get_alarms),
    _: User = Depends(require_roles("admin", "operator")),
) -> dict:
    s = db.get(Sensor, sensor_id)
    if not s:
        raise NotFound("传感器不存在")
    r = SensorReading(sensor_id=sensor_id, value=body.value,
                      ts=body.ts or datetime.now(), source=body.source)
    db.add(r)
    db.commit()
    db.refresh(r)

    level, msg = _judge(s, body.value)
    raised = None
    if level:
        raised = store.raise_external(
            metric=f"env_{s.kind}_{s.id}_{level}", level=level, message=msg, value=body.value,
        )
        if raised is not None:
            from app.services.messages import store as msg_store
            msg_store.add("warn" if level == "warn" else "danger", "alarm",
                          f"环境超限：{s.name}", msg,
                          {"to": "alarms", "query": {"status": "unacked"}})
    return {"ok": True, "id": r.id, "level": level, "message": msg, "raised": raised is not None}


def _judge(s: Sensor, value: float) -> tuple[str | None, str]:
    unit = s.unit or KINDS.get(s.kind, {}).get("unit", "")
    if s.crit_high is not None and value >= s.crit_high:
        return "critical", f"{s.name} 超严重上限：{value}{unit}（≥{s.crit_high}）"
    if s.crit_low is not None and value <= s.crit_low:
        return "critical", f"{s.name} 低于严重下限：{value}{unit}（≤{s.crit_low}）"
    if s.warn_high is not None and value >= s.warn_high:
        return "warn", f"{s.name} 超提醒上限：{value}{unit}（≥{s.warn_high}）"
    if s.warn_low is not None and value <= s.warn_low:
        return "warn", f"{s.name} 低于提醒下限：{value}{unit}（≤{s.warn_low}）"
    return None, ""


@router.get("/{sensor_id}/history")
def history(
    sensor_id: int,
    hours: int = Query(24, ge=1, le=24 * 30),
    points: int = Query(120, ge=10, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    s = db.get(Sensor, sensor_id)
    if not s:
        raise NotFound("传感器不存在")
    since = datetime.now() - timedelta(hours=hours)
    rows = db.scalars(
        select(SensorReading).where(SensorReading.sensor_id == sensor_id,
                                    SensorReading.ts >= since)
        .order_by(SensorReading.ts)
    ).all()
    if not rows:
        return {"sensor_id": sensor_id, "unit": s.unit, "points": [], "count": 0}

    # 等间隔降采样：把时间轴切成 points 段，每段取平均
    span = (rows[-1].ts - rows[0].ts).total_seconds() or 1
    bucket = max(span / points, 1.0)
    agg: dict[int, list[float]] = {}
    for r in rows:
        idx = int((r.ts - rows[0].ts).total_seconds() // bucket)
        agg.setdefault(idx, []).append(r.value)
    series = [
        {"ts": (rows[0].ts + timedelta(seconds=i * bucket)).isoformat(timespec="seconds"),
         "value": round(sum(v) / len(v), 3)}
        for i, v in sorted(agg.items())
    ]
    return {"sensor_id": sensor_id, "unit": s.unit, "points": series, "count": len(rows)}


@router.get("/summary")
def summary(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """首页环境面板用：每类传感器取最新一条。"""
    out: dict[str, Any] = {}
    for s in db.query(Sensor).filter(Sensor.enabled.is_(True)).all():
        latest = db.scalars(
            select(SensorReading).where(SensorReading.sensor_id == s.id)
            .order_by(SensorReading.ts.desc()).limit(1)
        ).first()
        out[s.kind] = {
            "name": s.name, "unit": s.unit,
            "value": latest.value if latest else None,
            "ts": latest.ts.isoformat(timespec="seconds") if latest else None,
            "calibrated": any(v is not None for v in (s.warn_low, s.warn_high, s.crit_low, s.crit_high)),
        }
    return {"items": out, "count": len(out)}
