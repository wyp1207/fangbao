from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.adapters.jcrob.units import parse_nav_points
from app.api.deps import get_adapter, get_cache, get_current_user, require_csrf, require_roles
from app.core.errors import BadRequest, NotFound
from app.db.session import get_db
from app.models.robot import Robot
from app.models.user import User
from app.services.async_bridge import run_async
from app.services.command_gateway import precheck as run_precheck
from app.services.messages import audit

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


@router.post("/{robot_id}/motion", dependencies=[Depends(require_csrf)])
def motion(
    robot_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    """起立 / 趴下（X30 是切换指令；JCROB 暂不支持）。写开关保护。"""
    from app.services.task_dispatch import _require_write

    _require_write()
    action = str(body.get("action") or "").lower()
    if action not in ("stand", "lie"):
        raise BadRequest("action 只能是 stand / lie", code="BAD_ACTION")
    robot = db.get(Robot, robot_id)
    if not robot:
        raise NotFound("设备不存在")

    from app.adapters.registry import build_for
    import asyncio

    from app.core.config import get_settings

    adapter, _ = build_for(robot, settings=get_settings())
    fn = getattr(adapter, action, None)
    if fn is None:
        raise BadRequest(f"适配器 {robot.adapter} 不支持 {action}", code="NOT_SUPPORTED")
    res = fn()
    if hasattr(res, "__await__"):
        res = run_async(res)
    audit(db=db, action=f"robot.{action}", target=robot.name, user=me)
    return {"ok": True, "result": res}


@router.get("/{robot_id}/status")
def robot_status(robot_id: int, cache=Depends(get_cache),
                 _user: User = Depends(get_current_user)) -> dict:
    """聚合状态：按设备 id 读各自的轮询缓存，不在这里同步调机器人。"""
    from app.services.robot_runtime import registry as robot_registry

    rt = robot_registry.get(robot_id)
    if rt is None:
        # 未注册的设备（未启用/不存在）回落到默认缓存，前端不至于白屏
        return cache.as_dict()
    data = rt.cache.as_dict()
    data["robot_id"] = rt.robot_id
    data["robot_name"] = rt.name
    if rt.error:
        data["runtime_error"] = rt.error
    # 环境传感器是机器人推的 WS，状态单独给一份（前端能看出"流断没断"）
    try:
        from app.services.env_ws import state_for

        data["env_ws"] = state_for(robot_id)
    except Exception:  # noqa: BLE001
        data["env_ws"] = {"supported": False}
    return data


def verify_initial_pose(status: dict | None, x: float, y: float,
                        tolerance_m: float = 0.5) -> dict:
    """重置定位后的校验：located=true 且位姿与目标差 ≤ 容差。

    单独抽出来是因为这段数学错了没人看得出来——界面只会显示"已重置"。
    """
    st = status or {}
    located = st.get("located")
    pose = st.get("pose") or {}
    dist = None
    if pose.get("x") is not None and pose.get("y") is not None:
        dist = round(((float(pose["x"]) - x) ** 2 + (float(pose["y"]) - y) ** 2) ** 0.5, 2)
    verified = bool(located) and (dist is None or dist <= tolerance_m)
    if verified:
        note = ""
    elif not located:
        note = "定位未就绪（located=false）"
    elif dist is not None:
        note = f"位姿与目标差 {dist}m，超过 {tolerance_m}m"
    else:
        note = "读不到位姿"
    return {"verified": verified, "located": located, "distance_m": dist, "note": note}


@router.post("/{robot_id}/init-loc", dependencies=[Depends(require_csrf)])
def init_location(
    robot_id: int,
    body: dict,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator", "safety")),
) -> dict:
    """重置机器人定位（X30 协议 2101）。

    现场什么时候用：断电重启后、机器人被搬动过、切换地图后。
    不重置的话位姿和地图对不上，巡航会"到不了点"。
    """
    from app.services.task_dispatch import _require_write

    _require_write()
    robot = db.get(Robot, robot_id)
    if not robot:
        raise NotFound("设备不存在")

    from app.adapters.registry import build_for
    from app.core.config import get_settings

    adapter, err = build_for(robot, settings=get_settings())
    if err:
        raise BadRequest(err, code="ADAPTER_UNAVAILABLE")
    fn = getattr(adapter, "set_initial_pose", None)
    if fn is None:
        raise BadRequest(f"适配器 {robot.adapter} 不支持重置定位", code="NOT_SUPPORTED")

    x = float(body.get("x") or 0)
    y = float(body.get("y") or 0)
    yaw = float(body.get("yaw") or 0)
    res = fn(x, y, yaw)
    if hasattr(res, "__await__"):
        res = run_async(res)

    # 发出去不等于生效：等 2 秒读回一次，确认 located=true 且位姿接近目标。
    # 不校验的话，界面提示"已重置"，实际机器人还站在旧位姿上（比不提示更糟）。
    import time as _t

    _t.sleep(2)
    verified = None
    located = None
    dist = None
    note = ""
    try:
        probe = run_async(adapter.get_status(), timeout=8) if hasattr(adapter, "get_status") else None
        check = verify_initial_pose(probe, x, y)
        verified, located, dist, note = (check["verified"], check["located"],
                                        check["distance_m"], check["note"])
    except Exception as exc:  # noqa: BLE001
        note = f"读回校验失败：{exc.__class__.__name__}"

    audit(db=db, action="robot.init_loc", target=robot.name, user=me,
          detail={"x": x, "y": y, "yaw": yaw, "verified": verified, "dist_m": dist})
    return {"ok": True, "x": x, "y": y, "yaw": yaw, "result": res,
            "verified": verified, "located": located, "distance_m": dist, "note": note}


@router.post("/{robot_id}/takeover", dependencies=[Depends(require_csrf)])
def takeover_robot(
    robot_id: int,
    body: dict | None = None,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator", "safety")),
) -> dict:
    """人工接管：取消这台车所有运行中的任务，把控制权交给人。"""
    from app.services.task_lock import takeover

    reason = (body or {}).get("reason") or f"人工接管（{me.username}）"

    # 先给机器人发取消，别只改数据库（否则页面显示"已接管"、车还在跑）
    stopped = None
    try:
        from app.services.robot_runtime import registry as _reg

        rt = _reg.get(robot_id)
        if rt is not None and rt.adapter is not None and hasattr(rt.adapter, "cancel"):
            res = rt.adapter.cancel()
            if hasattr(res, "__await__"):
                res = run_async(res)
            stopped = True
    except Exception:  # noqa: BLE001
        stopped = False

    n = takeover(db, robot_id, reason=reason)
    audit(db=db, action="robot.takeover", target=f"robot:{robot_id}", user=me,
          detail={"cancelled_runs": n, "reason": reason, "robot_cancel_sent": stopped})
    return {"ok": True, "cancelled": n, "reason": reason, "robot_cancel_sent": stopped}


@router.get("/runtime")
def runtime_list(_user: User = Depends(get_current_user)) -> list[dict]:
    """所有设备的运行时状态（哪台在轮询、哪台适配器没实现）。"""
    from app.services.robot_runtime import registry as robot_registry

    return [rt.status() for rt in robot_registry.runtimes.values()]


@router.get("/{robot_id}/pose")
def robot_pose(robot_id: int, cache=Depends(get_cache),
               _user: User = Depends(get_current_user)) -> dict:
    """和 /status 读同一个数据源，避免"状态说在线、位姿说离线"。"""
    from app.services.robot_runtime import registry as robot_registry

    rt = robot_registry.get(robot_id)
    src = rt.cache if rt is not None else cache
    snap = src.as_dict()
    return {"pose": snap.get("pose") or {}, "age_s": snap["age_s"], "online": snap["online"]}


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
    """能力 = 外设派生 + 适配器探测结果（派生为准，探测只补充版本信息）。"""
    from app.models.peripheral import Peripheral
    from app.services.capabilities import derive

    robot = _robot_or_default(db, robot_id)
    periphs = db.query(Peripheral).filter(Peripheral.robot_id == robot.id).all()
    data = derive(robot, periphs)
    probed = {}
    if robot.capabilities_json:
        try:
            parsed = json.loads(robot.capabilities_json)
            if isinstance(parsed, dict):
                probed = parsed
        except Exception:  # noqa: BLE001
            probed = {}
    data["probed"] = bool(probed)
    data["probe"] = probed
    return data


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
