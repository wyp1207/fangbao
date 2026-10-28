"""单点导航（点哪去哪）：校验 + 下发 + 审计。

安全闸门（与 GLM/豆包评审一致）：
1) 写开关
2) 设备在线、非急停、电量 ≥ 20%、没有正在跑的任务
3) 目标点必须在**当前激活地图**内，且不是障碍/未知区域
4) 单次距离超过设置上限（默认 50m）→ 409 要求确认（confirmed=true）
5) 落审计 robot.goto
"""

from __future__ import annotations

import math

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_csrf, require_roles
from app.core.errors import BadRequest, NotFound, PlatformError
from app.db.session import get_db
from app.models.map_library import PlatformMap
from app.models.robot import Robot
from app.models.user import User
from app.services.map_check import check_point_free, current_map_id
from app.services.messages import audit

router = APIRouter(tags=["robot-goto"])

GOTO_DEFAULT_MAX_M = 50.0


@router.post("/robots/{robot_id}/goto", dependencies=[Depends(require_csrf)])
def goto_point(
    robot_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator", "safety")),
) -> dict:
    from app.services.robot_runtime import registry
    from app.services.task_dispatch import _require_write
    from app.services.task_lock import active_run

    _require_write()
    robot = db.get(Robot, robot_id)
    if robot is None:
        raise NotFound("设备不存在")

    try:
        x = float(body.get("x"))
        y = float(body.get("y"))
    except (TypeError, ValueError):
        raise BadRequest("x/y 必须是数字", code="BAD_COORDS") from None
    yaw = float(body.get("yaw") or 0.0)
    confirmed = bool(body.get("confirmed"))

    rt = registry.get(robot_id)
    if rt is None or rt.adapter is None:
        raise BadRequest("该设备没有可用适配器（未启用或未实现）", code="NO_ADAPTER")
    snap = rt.cache.as_dict()
    if not snap.get("online"):
        raise PlatformError("设备离线，不能下发", code="ROBOT_OFFLINE", status_code=409)
    status = snap.get("status") or {}
    if status.get("estop"):
        raise PlatformError("设备处于急停状态，先解除急停", code="ESTOP", status_code=409)
    battery = (snap.get("info") or {}).get("battery")
    if isinstance(battery, (int, float)) and battery < 20:
        raise PlatformError(f"电量 {battery}% 低于 20%，先回充", code="LOW_BATTERY",
                            status_code=409)
    busy = active_run(db, robot_id)
    if busy:
        raise PlatformError(f"这台车正在执行任务 #{busy['id']}「{busy['name']}」，"
                            f"先停止或接管", code="RUN_BUSY", status_code=409)

    # 地图校验：目标必须落在当前地图内，且不是障碍/未知
    map_id = current_map_id(db, robot)
    ok, why = check_point_free(db, map_id, x, y)
    if not ok:
        raise PlatformError(f"目标点不可达：{why}", code="POINT_INVALID", status_code=409)

    # 距离上限（防误触跨区）
    pose = snap.get("pose") or {}
    dist = None
    if pose.get("x") is not None and pose.get("y") is not None:
        dist = math.hypot(x - float(pose["x"]), y - float(pose["y"]))
        limit = float(body.get("max_m") or GOTO_DEFAULT_MAX_M)
        if dist > limit and not confirmed:
            raise PlatformError(
                f"目标距离 {dist:.1f}m 超过 {limit:.0f}m，需要二次确认（confirmed=true）",
                code="NEED_CONFIRM", status_code=409)

    res = rt.adapter.goto(x, y, yaw)
    if hasattr(res, "__await__"):
        from app.services.async_bridge import run_async

        res = run_async(res, timeout=30)

    audit(db=db, action="robot.goto", target=robot.name, user=me,
          detail={"x": x, "y": y, "yaw": yaw, "distance_m": round(dist, 2) if dist else None,
                  "map_id": map_id})
    return {"ok": True, "x": x, "y": y, "yaw": yaw,
            "distance_m": round(dist, 2) if dist is not None else None,
            "map_id": map_id, "accepted": True, "raw": res}
