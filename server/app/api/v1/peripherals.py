"""外设管理接口：现场加装/更换硬件后，页面自动跟着变。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_csrf, require_roles
from app.core.errors import BadRequest, NotFound
from app.db.session import get_db
from app.models.peripheral import Peripheral
from app.models.robot import Robot
from app.models.user import User
from app.services.capabilities import derive
from app.services.messages import audit

router = APIRouter(tags=["peripherals"])

KINDS = ("camera", "thermal", "ptz", "gas", "sf6", "env", "temp", "humidity", "noise", "dust", "speaker")


def _out(p: Peripheral) -> dict:
    return {
        "id": p.id, "robot_id": p.robot_id, "kind": p.kind, "vendor": p.vendor,
        "model": p.model, "channel": p.channel, "sensor_id": p.sensor_id,
        "video_id": p.video_id, "enabled": p.enabled,
        "config": json.loads(p.config_json) if p.config_json else None,
    }


@router.get("/peripherals")
def list_peripherals(
    robot_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    q = db.query(Peripheral)
    if robot_id is not None:
        q = q.filter(Peripheral.robot_id == robot_id)
    return [_out(p) for p in q.order_by(Peripheral.id).all()]


@router.post("/peripherals", dependencies=[Depends(require_csrf)])
def create_peripheral(
    body: dict,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "sysadmin")),
) -> dict:
    kind = str(body.get("kind") or "")
    if kind not in KINDS:
        raise BadRequest(f"kind 只支持 {KINDS}", code="BAD_KIND")
    robot = db.get(Robot, int(body.get("robot_id") or 0))
    if robot is None:
        raise NotFound("设备不存在")

    p = Peripheral(
        robot_id=robot.id, kind=kind, vendor=body.get("vendor"),
        model=body.get("model"), channel=body.get("channel"),
        config_json=json.dumps(body.get("config") or {}, ensure_ascii=False),
        sensor_id=body.get("sensor_id"), video_id=body.get("video_id"),
        enabled=bool(body.get("enabled", True)),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    audit(db=db, action="peripheral.create", target=f"{robot.name}/{kind}", user=me)
    return _out(p)


@router.patch("/peripherals/{pid}", dependencies=[Depends(require_csrf)])
def update_peripheral(
    pid: int, body: dict,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "sysadmin")),
) -> dict:
    p = db.get(Peripheral, pid)
    if p is None:
        raise NotFound("外设不存在")
    for k in ("vendor", "model", "channel", "sensor_id", "video_id", "enabled"):
        if k in body:
            setattr(p, k, body[k])
    if "config" in body:
        p.config_json = json.dumps(body["config"] or {}, ensure_ascii=False)
    db.commit()
    audit(db=db, action="peripheral.update", target=str(pid), user=me)
    return _out(p)


@router.delete("/peripherals/{pid}", dependencies=[Depends(require_csrf)])
def delete_peripheral(
    pid: int, db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "sysadmin")),
) -> dict:
    p = db.get(Peripheral, pid)
    if p is None:
        raise NotFound("外设不存在")
    db.delete(p)
    db.commit()
    audit(db=db, action="peripheral.delete", target=str(pid), user=me)
    return {"ok": True}


@router.get("/robots/{robot_id}/capabilities")
def robot_capabilities(
    robot_id: int, db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """能力由外设派生（不再读手填的 capabilities_json 作为事实来源）。"""
    robot = db.get(Robot, robot_id)
    if robot is None:
        raise NotFound("设备不存在")
    periphs = db.query(Peripheral).filter(Peripheral.robot_id == robot_id).all()
    return derive(robot, periphs)
