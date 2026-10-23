"""传感器读数入库 + 判阈值的唯一入口。

手工录入、API Key 推送、Modbus/MQTT 采集都走这里——
否则三套逻辑各写一遍，早晚出现"页面上能报警、网关上不报警"。
"""

from __future__ import annotations

from datetime import datetime

from app.models.sensor import Sensor, SensorReading


def judge(s: Sensor, value: float) -> tuple[str | None, str]:
    from app.api.v1.sensors import _judge  # 复用已有的阈值判断

    return _judge(s, value)


def _rule_for(db, s: Sensor) -> dict:
    """取这条传感器所属外设上的告警规则（没有就回落到传感器自身阈值）。"""
    import json

    from app.models.peripheral import Peripheral

    p = (db.query(Peripheral)
         .filter(Peripheral.sensor_id == s.id, Peripheral.enabled.is_(True))
         .first())
    if p is None or not p.config_json:
        return {"robot_id": p.robot_id if p else None}
    try:
        cfg = json.loads(p.config_json or "{}")
    except Exception:  # noqa: BLE001
        cfg = {}
    rule = cfg.get("rule") or {}
    rule["robot_id"] = p.robot_id
    return rule


def _judge_with_rule(s: Sensor, value: float, rule: dict) -> tuple[str | None, str]:
    """外设规则优先：enabled=false 不报；阈值覆盖传感器默认值。"""
    if rule.get("enabled") is False:
        return None, "该外设已关闭告警"

    class _Tmp:
        pass

    t = _Tmp()
    for f in ("warn_high", "crit_high", "warn_low", "crit_low", "name", "unit", "kind"):
        setattr(t, f, rule.get(f) if rule.get(f) is not None else getattr(s, f))
    from app.api.v1.sensors import _judge

    return _judge(t, value)


def ingest_value(db, *, sensor_id: int, value: float, source: str = "gateway",
                 ts: datetime | None = None) -> dict:
    from app.api.v1.sensors import KINDS
    from app.services import alarms as alarms_mod

    s = db.get(Sensor, sensor_id)
    if s is None:
        return {"ok": False, "error": "sensor_not_found", "sensor_id": sensor_id}

    row = SensorReading(sensor_id=sensor_id, value=value, ts=ts or datetime.now(), source=source)
    db.add(row)
    db.commit()
    db.refresh(row)

    rule = _rule_for(db, s)
    level, msg = _judge_with_rule(s, value, rule)
    raised = None
    if level:
        store = alarms_mod.get_store()
        if store is not None:
            raised = store.raise_external(
                metric=f"env_{s.kind}_{s.id}_{level}", level=level, message=msg,
                value=value, robot_id=rule.get("robot_id"))
    return {"ok": True, "id": row.id, "level": level, "message": msg, "raised": raised is not None}
