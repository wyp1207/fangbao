from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.adapters.jcrob.units import parse_nav_points
from app.api.deps import get_adapter, get_cache, get_current_user, require_csrf, require_roles
from app.db.session import get_db
from app.models.robot import Robot
from app.models.user import User
from app.services.command_gateway import precheck as run_precheck

router = APIRouter(prefix="/robots", tags=["robots"])


def _robot_or_default(db: Session, robot_id: int) -> Robot:
    # 单机器人场景：库里没有就返回一个未落库的默认配置，只读用
    return db.get(Robot, robot_id) or Robot(id=robot_id, name="JCROB-01")


@router.get("")
def list_robots(db: Session = Depends(get_db), _user: User = Depends(get_current_user)) -> list[dict]:
    return [
        {"id": r.id, "name": r.name, "ip": r.ip, "port": r.port,
         "mode": r.mode, "version": r.version, "slam_type": r.slam_type,
         "last_seen": r.last_seen.isoformat() if r.last_seen else None}
        for r in db.query(Robot).all()
    ]


@router.get("/{robot_id}/status")
def robot_status(robot_id: int, cache=Depends(get_cache),
                 _user: User = Depends(get_current_user)) -> dict:
    """聚合状态：直接读 1s 轮询缓存，不在这里同步调机器人。"""
    return cache.as_dict()


@router.get("/{robot_id}/pose")
def robot_pose(robot_id: int, cache=Depends(get_cache),
               _user: User = Depends(get_current_user)) -> dict:
    return {"pose": cache.snapshot.pose, "age_s": cache.as_dict()["age_s"],
            "online": cache.online}


@router.get("/{robot_id}/maps")
async def list_maps(robot_id: int, adapter=Depends(get_adapter),
                    _user: User = Depends(get_current_user)):
    return await adapter.list_maps()


@router.get("/{robot_id}/map/current")
async def current_map(robot_id: int, adapter=Depends(get_adapter),
                      _user: User = Depends(get_current_user)):
    return await adapter.get_current_map()


@router.get("/{robot_id}/map/png")
async def map_png(robot_id: int, name: str = Query(..., min_length=1),
                  adapter=Depends(get_adapter),
                  _user: User = Depends(get_current_user)):
    png = await adapter.get_map_png(name)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@router.get("/{robot_id}/nav-points")
async def nav_points(robot_id: int, map_name: str = "", path_name: str = "",
                     adapter=Depends(get_adapter),
                     _user: User = Depends(get_current_user)) -> dict:
    """点位：服务端解析一次，前端不再重复实现解析器。

    同时保留 path_data 原文——写回时未修改的行要原样保留，不能整文件重排。
    """
    raw = await adapter.get_nav_points(map_name, path_name) or {}
    path_data = raw.get("path_data", "") or ""
    return {
        "map_name": raw.get("map_name", map_name),
        "path_name": raw.get("path_name", path_name),
        "points": parse_nav_points(path_data),
        "path_data": path_data,
    }


@router.get("/{robot_id}/tasks")
async def tasks(robot_id: int, adapter=Depends(get_adapter),
                _user: User = Depends(get_current_user)):
    return await adapter.get_tasks()


@router.get("/{robot_id}/capabilities")
def capabilities(robot_id: int, db: Session = Depends(get_db),
                 _user: User = Depends(get_current_user)) -> dict:
    robot = _robot_or_default(db, robot_id)
    if not robot.capabilities_json:
        return {"probed": False, "message": "还没探测过，POST /probe"}
    return {"probed": True, **json.loads(robot.capabilities_json)}


@router.post("/{robot_id}/probe", dependencies=[Depends(require_csrf)])
async def probe_robot(robot_id: int, db: Session = Depends(get_db),
                      adapter=Depends(get_adapter),
                      _user: User = Depends(require_roles("admin", "operator"))) -> dict:
    """重新做能力探测。只读接口，安全，但仍然记角色。"""
    try:
        caps = await adapter.probe_capabilities()
    except Exception as exc:  # noqa: BLE001 - 探测失败要留痕，再往上抛
        from app.services.messages import store as msg_store

        msg_store.add("danger", "system", "能力探测失败",
                      f"{exc.__class__.__name__}：接口不可达或返回异常",
                      {"to": "settings"})
        raise
    robot = db.get(Robot, robot_id)
    if robot:
        robot.capabilities_json = json.dumps(caps, ensure_ascii=False)
        robot.version = caps.get("version")
        robot.slam_type = caps.get("slam_type")
        db.commit()
    return caps


@router.post("/{robot_id}/commands/precheck", dependencies=[Depends(require_csrf)])
def precheck(robot_id: int, cache=Depends(get_cache),
             _user: User = Depends(require_roles("admin", "operator"))) -> dict:
    """写操作前置检查（只判断，不下发）。W1 用来验证闸门逻辑。"""
    snap = cache.snapshot
    reasons = run_precheck(status=snap.status, info=snap.info)
    return {"ok": not reasons, "reasons": reasons}
