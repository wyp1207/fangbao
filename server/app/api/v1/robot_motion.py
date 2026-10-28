"""车体基础运动（前进/后退/平移/转向）+ 起停切换。

安全设计（真机必须）：
- 写开关；MotionState 必须是站立/踏步（2/3/4）
- 单次 move 只发一帧轴指令，前端按住时 10Hz 重发；松手发零速
- 行进指令 1 秒没续发，机器人自身会因指令超时停下（厂家行为）
- 审计节流：2 秒内只记一条，避免刷爆审计表
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_adapter, require_csrf, require_roles
from app.core.errors import BadRequest, NotFound, PlatformError
from app.db.session import get_db
from app.models.robot import Robot
from app.models.user import User
from app.services.messages import audit

router = APIRouter(tags=["robot-motion"])

AXIS_FWD = 0x21010130
AXIS_LEFT = 0x21010131
AXIS_YAW = 0x21010135
CMD_START_STOP = 0x21010201

DEADZONE = 655          # 文档：|值| <= 655 视为 0
MAX_AXIS = 1000
_last_audit: dict[int, float] = {}


def _axis_value(norm: float) -> int:
    norm = max(-1.0, min(1.0, float(norm or 0)))
    if abs(norm) < 0.05:
        return 0
    # 映射到 (DEADZONE, MAX_AXIS]，保证"想动就真的超过死区"
    span = MAX_AXIS - DEADZONE
    return int(norm * span + (DEADZONE + 1) * (1 if norm > 0 else -1))


@router.post("/robots/{robot_id}/motion-mode", dependencies=[Depends(require_csrf)])
def motion_mode(
    robot_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    """开始/停止运动（踏步 <-> 站立），以及起立/趴下。"""
    from app.services.task_dispatch import _require_write

    _require_write()
    robot = db.get(Robot, robot_id)
    if robot is None:
        raise NotFound("设备不存在")
    action = str(body.get("action") or "").lower()
    if action not in ("stand", "lie", "start", "stop", "estop"):
        raise BadRequest("action 只能是 stand/lie/start/stop", code="BAD_ACTION")

    from app.adapters.registry import build_for
    from app.core.config import get_settings

    adapter, err = build_for(robot, settings=get_settings())
    if err:
        raise BadRequest(err, code="ADAPTER_UNAVAILABLE")
    if action == "estop":
        raise PlatformError("平台暂不支持远程软急停，请用随车急停按钮",
                            code="NOT_SUPPORTED", status_code=501)
    if action in ("stand", "lie"):
        fn = getattr(adapter, "stand" if action == "stand" else "lie", None)
        if fn is None:
            raise BadRequest(f"适配器不支持 {action}", code="NOT_SUPPORTED")
        res = fn()
        if hasattr(res, "__await__"):
            from app.services.async_bridge import run_async

            res = run_async(res)
        audit(db=db, action=f"robot.{action}", target=robot.name, user=me)
        return {"ok": True, "action": action, "raw": res}

    fn = getattr(adapter, "toggle_motion", None)
    if fn is None:
        raise BadRequest("适配器不支持开始/停止运动", code="NOT_SUPPORTED")
    res = fn()
    if hasattr(res, "__await__"):
        from app.services.async_bridge import run_async

        res = run_async(res)
    audit(db=db, action=f"robot.motion_{action}", target=robot.name, user=me,
          detail={"note": "toggle 语义，实际以 MotionState 回读为准"})
    return {"ok": True, "action": action, "raw": res}


@router.post("/robots/{robot_id}/move", dependencies=[Depends(require_csrf)])
def move(
    robot_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    """一帧速度指令。forward/left/yaw ∈ [-1,1]；松手请发 0。"""
    from app.services.task_dispatch import _require_write

    _require_write()
    robot = db.get(Robot, robot_id)
    if robot is None:
        raise NotFound("设备不存在")

    from app.services.robot_runtime import registry

    rt = registry.get(robot_id)
    if rt is None or rt.adapter is None:
        raise BadRequest("该设备没有可用适配器", code="NO_ADAPTER")
    st = (rt.cache.as_dict().get("status") or {})
    state = str(st.get("raw_state") or st.get("status") or "")
    # status 里我们存的是状态文本；MotionState 原始值在 snapshot 里
    motion_state = str(st.get("motion_state") or "")
    if motion_state and motion_state not in ("2", "3", "4"):
        raise PlatformError(f"当前 MotionState={motion_state}，先起立/开始运动再控制",
                            code="NOT_READY", status_code=409)

    fn = getattr(rt.adapter, "move_axis", None)
    if fn is None:
        raise BadRequest("适配器不支持速度控制", code="NOT_SUPPORTED")

    fwd = float(body.get("forward") or 0)
    left = float(body.get("left") or 0)
    yaw = float(body.get("yaw") or 0)
    fn(_axis_value(fwd), _axis_value(left), _axis_value(yaw))

    now = time.time()
    if now - _last_audit.get(robot_id, 0) > 2 and any(abs(v) > 0.05 for v in (fwd, left, yaw)):
        _last_audit[robot_id] = now
        audit(db=db, action="robot.move", target=robot.name, user=me,
              detail={"forward": round(fwd, 2), "left": round(left, 2), "yaw": round(yaw, 2)})
    return {"ok": True, "forward": fwd, "left": left, "yaw": yaw}
