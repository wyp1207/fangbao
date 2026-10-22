"""环境采集网关：配置 + 连通性测试 + 运行状态。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_csrf, require_roles
from app.core.errors import BadRequest, NotFound
from app.db.session import get_db
from app.models.sensor import Sensor
from app.models.sensor_gateway import SensorGateway
from app.models.user import User
from app.services.messages import audit

router = APIRouter(prefix="/sensor-gateways", tags=["sensor-gateways"])


class GatewayIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    protocol: str = Field(pattern="^(modbus|mqtt)$")
    host: str = Field(min_length=1, max_length=64)
    port: int = 502
    unit_id: int = 1
    topic: str | None = None
    username: str | None = None
    password: str | None = None
    mapping: list[dict] | dict | None = None
    interval_s: int = 10
    enabled: bool = True
    note: str | None = None


def _out(g: SensorGateway) -> dict:
    try:
        mapping = json.loads(g.mapping_json or "null")
    except Exception:  # noqa: BLE001
        mapping = None
    return {
        "id": g.id, "name": g.name, "protocol": g.protocol, "host": g.host,
        "port": g.port, "unit_id": g.unit_id, "topic": g.topic,
        "username": g.username, "mapping": mapping,
        "interval_s": g.interval_s, "enabled": g.enabled, "note": g.note,
        "created_at": g.created_at.isoformat(timespec="minutes") if g.created_at else None,
    }


def _validate(db: Session, body: GatewayIn) -> None:
    if body.protocol == "mqtt" and not body.topic:
        raise BadRequest("MQTT 网关必须填订阅主题", code="NO_TOPIC")
    if body.protocol == "modbus" and not body.mapping:
        raise BadRequest("Modbus 网关必须配置寄存器映射", code="NO_MAPPING")
    if isinstance(body.mapping, list):
        for m in body.mapping:
            if "sensor_id" not in m or "register" not in m:
                raise BadRequest("映射每项需要 sensor_id 与 register", code="BAD_MAPPING")
            if db.get(Sensor, int(m["sensor_id"])) is None:
                raise BadRequest(f"传感器 {m['sensor_id']} 不存在", code="NO_SENSOR")


@router.get("")
def list_gateways(db: Session = Depends(get_db),
                  _: User = Depends(require_roles("admin", "operator", "viewer"))) -> list[dict]:
    return [_out(g) for g in db.query(SensorGateway).order_by(SensorGateway.id.desc()).all()]


@router.post("", dependencies=[Depends(require_csrf)])
def create_gateway(body: GatewayIn, db: Session = Depends(get_db),
                   me: User = Depends(require_roles("admin", "operator"))) -> dict:
    _validate(db, body)
    g = SensorGateway(
        name=body.name.strip()[:64], protocol=body.protocol, host=body.host.strip(),
        port=body.port, unit_id=body.unit_id, topic=body.topic,
        username=body.username, password=body.password,
        mapping_json=json.dumps(body.mapping, ensure_ascii=False) if body.mapping else None,
        interval_s=max(body.interval_s, 3), enabled=body.enabled, note=body.note,
    )
    db.add(g)
    db.commit()
    db.refresh(g)
    audit(db=db, action="sensor_gateway.create", target=g.name, user=me,
          detail={"protocol": g.protocol, "host": g.host})
    _restart_runner()
    return _out(g)


@router.delete("/{gid}", dependencies=[Depends(require_csrf)])
def delete_gateway(gid: int, db: Session = Depends(get_db),
                   me: User = Depends(require_roles("admin"))) -> dict:
    g = db.get(SensorGateway, gid)
    if not g:
        raise NotFound("网关不存在")
    db.delete(g)
    db.commit()
    audit(db=db, action="sensor_gateway.delete", target=g.name, user=me)
    return {"ok": True}


@router.post("/{gid}/test", dependencies=[Depends(require_csrf)])
def test_gateway(gid: int, db: Session = Depends(get_db),
                 _: User = Depends(require_roles("admin", "operator"))) -> dict:
    """真读一次：Modbus 读第一个寄存器；MQTT 只测 TCP 连通（订阅要起连接，不适合同步测）。"""
    g = db.get(SensorGateway, gid)
    if not g:
        raise NotFound("网关不存在")
    if g.protocol == "modbus":
        from app.services.sensor_gateway import modbus_read, scale

        mapping = json.loads(g.mapping_json or "[]")
        if not mapping:
            raise BadRequest("没有映射，无法测试", code="NO_MAPPING")
        first = mapping[0]
        try:
            regs = modbus_read(g.host, int(g.port), int(g.unit_id or 1),
                               int(first["register"]), 1,
                               function=int(first.get("function", 3)))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}
        return {"ok": True, "raw": regs[0], "value": scale(regs[0], first),
                "sensor_id": first["sensor_id"]}

    import socket

    try:
        with socket.create_connection((g.host, int(g.port)), timeout=3):
            pass
        return {"ok": True, "note": "TCP 可达；实际订阅状态见运行状态"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}


@router.get("/runtime")
def runtime(_: User = Depends(require_roles("admin", "operator", "viewer"))) -> list[dict]:
    from app.services import sensor_gateway as sg

    return sg.runner.status() if sg.runner is not None else []


def _restart_runner() -> None:
    from app.services import sensor_gateway as sg

    if sg.runner is not None:
        sg.runner.stop_all()
        sg.runner = sg.SensorGatewayRunner(sg.runner._sf)  # noqa: SLF001
        sg.runner.start_all()
