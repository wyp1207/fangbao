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

    # 能力声明：平台只读这里，不判断厂商（B 项）。
    # X30 的 1003 一次只能给一个目标点，天然逐点；真机确认后只改布尔值。
    capabilities = {
        "supports_batch": False,
        "supports_inline_actions": False,
        "supports_pause": False,
        "cancel_semantics": "sync",
    }
    # 实测：30000 的响应时间在 0.15~8s 之间波动（导航主机单线程处理），
    # 所以轮询放慢到 3s，超时放宽，宁可数据旧一点也不要一直超时。
    poll_interval = 5.0
    # 30000 单次响应 0.2~8s，所以判离线的时间也要放宽，否则会频繁误报
    offline_after_s = 30.0

    def __init__(self, host: str, port: int = 30000, timeout: float = 5.0,
                 motion_host: str = "192.168.1.103") -> None:
        self.client = X30Client(host, port, timeout)
        self.motion_host = motion_host
        # 30000 是短连接请求/响应，一次轮询里 4 个方法各开一条连接会被机器人拖垮
        # （实测：第二、三条经常超时）。这里加 0.8s 缓存，一轮只打一次。
        self._status_cache: tuple[float, dict] | None = None
        self._battery_cache: tuple[float, dict] | None = None

    def _cached(self, key: str, fn, ttl: float = 10.0) -> dict:
        import time

        cache = getattr(self, f"_{key}_cache")
        if cache is not None and time.time() - cache[0] < ttl:
            return cache[1]
        data = fn()
        setattr(self, f"_{key}_cache", (time.time(), data))
        return data

    async def aclose(self) -> None:
        return None

    def _call(self, fn, *a, **kw):
        return asyncio.to_thread(fn, *a, **kw)

    # ---- 只读 ----
    async def get_status(self) -> dict:
        r = await self._call(self._cached, "status", self.client.status)
        state = MOTION_STATES.get(str(r.get("MotionState", "")), r.get("MotionState", "未知"))
        return {
            "status": state,
            "located": str(r.get("Location", "")).strip() == "1",
            "raw": r,
        }

    async def get_info(self) -> dict:
        r = await self._call(self._cached, "status", self.client.status)
        b = await self._call(self._cached, "battery", self.client.battery, 120.0)
        battery = _num(r.get("Electricity"))
        if battery is None:
            battery = _num(b.get("BatteryLevel"))
        return {
            "battery": battery,
            "voltage": _num(b.get("Voltage")),
            "motion_state": MOTION_STATES.get(str(r.get("MotionState", "")), "未知"),
            "charged": str(r.get("ChargeState", "")) == "1",
            "raw": {**r, **b},
        }

    async def get_pose(self) -> dict:
        r = await self._call(self._cached, "status", self.client.status)
        x, y, yaw = _num(r.get("PosX")), _num(r.get("PosY")), _num(r.get("Yaw"))
        return {"x": x, "y": y, "angle_deg": yaw, "raw": r}

    async def get_galileo(self) -> dict:
        r = await self._call(self._cached, "status", self.client.status)
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
    def dispatch(self, order: dict) -> dict:
        """后台串行执行所有点位，立即返回 RUNNING（1003 是长阻塞接口，不能等）。

        上一版把 photo/thermal/wait 当"非导航"跳过 → 模板一条导航都不发；
        且同步返回 FINISHED → 轮询线程不再补步骤状态。这里改成后台线程逐点跑。
        """
        actions = order.get("actions") or []
        if not actions:
            return {"id": "", "state": "FAILED"}

        import threading

        t = threading.Thread(target=self._run_order_bg, args=(order,),
                             daemon=True, name="x30-order")
        t.start()
        return {"id": str(order.get("orderId") or ""), "state": "RUNNING",
                "raw": {"accepted": True, "points": len(actions)}}

    def _run_order_bg(self, order: dict) -> None:
        import asyncio
        import logging

        log = logging.getLogger(__name__)
        try:
            asyncio.run(self._execute_order(order))
        except Exception:  # noqa: BLE001
            log.exception("X30 多点任务执行失败 order=%s", order.get("orderId"))

    async def _execute_order(self, order: dict) -> None:
        import asyncio
        import logging

        log = logging.getLogger(__name__)
        for act in order.get("actions") or []:
            params = {p.get("key"): p.get("value") for p in act.get("actionParameters", [])}
            if params.get("x") is None or params.get("y") is None:
                continue          # 没有坐标的动作（纯拍照）不在车端执行
            x = _num(params.get("x")) or 0.0
            y = _num(params.get("y")) or 0.0
            yaw = _num(params.get("yaw")) or 0.0
            try:
                await self._call(self.client.nav_goal, x, y, yaw)
            except (TimeoutError, OSError):
                # 1003 要等任务跑完才回；超时=已受理，进度靠 1007
                log.info("X30 nav_goal 超时（按已受理处理）x=%s y=%s", x, y)
            for _ in range(80):
                try:
                    st = await self._call(self.client.nav_status)
                except Exception:  # noqa: BLE001
                    await asyncio.sleep(3)
                    continue
                status = str(st.get("Status", ""))
                if status == "0":
                    break
                if status == "-1":
                    log.warning("X30 点位失败 x=%s y=%s raw=%s", x, y, st)
                    return
                await asyncio.sleep(3)

    async def goto(self, x: float, y: float, yaw: float = 0.0) -> dict:
        # 1003 的响应要等任务跑完才回（官方文档 2.2 的【注意】）。
        # 这里用短超时发出去就算"已受理"，进度靠 1007 轮询。
        try:
            r = await self._call(self.client.nav_goal, x, y, yaw)
        except (TimeoutError, OSError):
            return {"id": "x30-nav", "state": "RUNNING", "raw": {"accepted": True}}
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

    # ---- 到点抓拍（证据）----
    async def capture(self, step=None, stream: str | None = None) -> dict:
        """到点抓一张图存本地。stream 由调用方从外设里挑（camera kind）。"""
        from app.core.config import get_settings
        from app.services.snapshot import capture_frame

        if not stream:
            raise RuntimeError("这台设备没有配置相机外设（camera）")
        return await self._call(capture_frame, stream, get_settings().go2rtc_base)

    # ---- 现场动作 ----
    # ---- 地图/点位：X30 的地图由导航主机管理，平台侧暂不读写 ----
    # 返回空而不是抛异常：前端会显示"没有点位"，而不是 500。
    async def get_nav_points(self) -> list:
        return []

    async def get_current_map(self) -> dict:
        return {}

    async def get_map_png(self) -> bytes:
        return b""

    async def list_maps(self) -> list:
        return []

    async def set_initial_pose(self, x: float, y: float, yaw: float = 0.0) -> dict:
        """重置定位（协议 2101）。断电/被搬动/地图切换后必须做，否则导航会跑偏。"""
        return await self._call(self.client.init_loc, x, y, yaw)

    async def stand(self) -> dict:
        """起立/趴下是切换指令：趴下时发起立，站立时发就是趴下。"""
        from app.adapters.deeprobotics.protocol import CMD_STAND_LIE, send_motion

        return await self._call(send_motion, CMD_STAND_LIE, self.motion_host)

    async def lie(self) -> dict:
        return await self.stand()
