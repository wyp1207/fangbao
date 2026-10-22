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

    level, msg = judge(s, value)
    raised = None
    if level:
        store = alarms_mod.get_store()
        if store is not None:
            raised = store.raise_external(
                metric=f"env_{s.kind}_{s.id}_{level}", level=level, message=msg, value=value)
    return {"ok": True, "id": row.id, "level": level, "message": msg, "raised": raised is not None}
