"""X30 适配器：把本体监控协议映射成平台统一结构。

字段名来自现场已验证的桥接实现（8.40 上 robot-flask/dispatch.py），
不是按文档猜的：
  1002 → MotionState / Electricity / PosX / PosY / Yaw / Speed / Location
  2001 → BatteryLevel / Voltage
  1007 → Status（0 完成 / 1 执行中 / -1 无法执行）

写操作（导航/起立趴下/初始化定位）通过上层 `robot.write_enabled` 开关控制，
适配器本身不判断权限。
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.adapters.deeprobotics.protocol import (
    MOTION_LIE, MOTION_STAND, MOTION_STATES, NAV_STATES, X30Client,
)


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class DeepRoboticsX30Adapter:
    mode = "x30"

    def __init__(self, host: str, port: int = 30000, timeout: float = 5.0) -> None:
        self.client = X30Client(host, port, timeout)

    async def aclose(self) -> None:
        return None

    def _call(self, fn, *a, **kw):
        return asyncio.to_thread(fn, *a, **kw)

    # ---- 只读 ----
    async def get_status(self) -> dict:
        r = await self._call(self.client.status)
        state = MOTION_STATES.get(str(r.get("MotionState", "")), r.get("MotionState", "未知"))
        return {
            "status": {
                "status": state,
                "located": str(r.get("Location", "")).lower() in ("1", "true", "ok"),
                "raw": r,
            }
        }

    async def get_info(self) -> dict:
        r = await self._call(self.client.status)
        b = await self._call(self.client.battery)
        battery = _num(r.get("Electricity"))
        if battery is None:
            battery = _num(b.get("BatteryLevel"))
        return {
            "info": {
                "battery": battery,
                "voltage": _num(b.get("Voltage")),
                "motion_state": MOTION_STATES.get(str(r.get("MotionState", "")), "未知"),
                "raw": {**r, **b},
            }
        }

    async def get_pose(self) -> dict:
        r = await self._call(self.client.status)
        x, y, yaw = _num(r.get("PosX")), _num(r.get("PosY")), _num(r.get("Yaw"))
        return {"x": x, "y": y, "angle_deg": yaw, "raw": r}

    async def get_galileo(self) -> dict:
        r = await self._call(self.client.status)
        return {"currentSpeedX": _num(r.get("Speed")), "raw": r}

    async def get_tasks(self) -> Any:
        # X30 的任务在导航主机里，1007 只给当前任务状态
        r = await self._call(self.client.nav_status)
        return [{
            "id": "x30-current",
            "name": "当前导航任务",
            "state": NAV_STATES.get(str(r.get("Status", "")), "未知"),
            "raw": r,
        }]

    async def list_maps(self) -> Any:
        # 地图列表在导航主机上，需 ROS 话题；先返回空，不假装有
        return []

    async def probe_capabilities(self) -> dict:
        try:
            r = await self._call(self.client.status)
            ok = bool(r)
        except Exception as exc:  # noqa: BLE001
            return {"probed": False, "error": f"{exc.__class__.__name__}: {exc}"}
        return {
            "probed": True,
            "version": "unknown",
            "port": self.client.port,
            "magic": (self.client.last_magic or b"").hex(),
            "supports": {"info": ok, "pose": ok, "nav": True, "write": True},
            "note": "读状态已通；写操作需开启 robot.write_enabled 并现场授权",
        }

    # ---- 写 ----
    async def dispatch(self, order: dict) -> dict:
        actions = order.get("actions") or []
        if not actions:
            return {"id": "", "state": "FAILED"}
        first = actions[0]
        params = {p.get("key"): p.get("value") for p in first.get("actionParameters", [])}
        x = _num(params.get("x")) or 0.0
        y = _num(params.get("y")) or 0.0
        yaw = _num(params.get("yaw")) or 0.0
        r = await self._call(self.client.nav_goal, x, y, yaw)
        ok = "_error" not in r
        return {"id": order.get("orderId", ""), "state": "RUNNING" if ok else "FAILED", "raw": r}

    async def goto(self, x: float, y: float, yaw: float = 0.0) -> dict:
        r = await self._call(self.client.nav_goal, x, y, yaw)
        return {"id": "x30-nav", "state": "FAILED" if "_error" in r else "RUNNING", "raw": r}

    async def pause(self) -> dict:
        # X30 没有独立"暂停"命令：到达前取消 = 停，重新下发 = 继续
        return await self._call(self.client.cancel)

    async def resume(self) -> dict:
        return {"note": "X30 无独立继续命令，需重新下发目标点"}

    async def cancel(self) -> dict:
        return await self._call(self.client.cancel)

    async def get_order(self) -> dict:
        r = await self._call(self.client.nav_status)
        st = str(r.get("Status", ""))
        state = {"0": "FINISHED", "1": "RUNNING", "-1": "FAILED"}.get(st, "UNKNOWN")
        return {"state": state, "raw": r}

    # ---- 现场动作 ----
    async def stand(self) -> dict:
        return await self._call(self.client.motion, MOTION_STAND)

    async def lie(self) -> dict:
        return await self._call(self.client.motion, MOTION_LIE)
