"""真机 HTTP Adapter（只读部分）。

写操作（任务下发/充电/IO/遥控）本期不实现；CommandGateway 在 services/ 里留了闸门骨架，
等 11/10 真机联调、采集表第 15–17 行签字后再开。
"""

from __future__ import annotations

import asyncio

import logging
from typing import Any

from app.adapters.jcrob import errors as jerr
from app.adapters.jcrob.capability import probe
from app.adapters.jcrob.client import JcrobHttpClient
from app.adapters.jcrob.config_view import project_config
from app.adapters.jcrob.units import AngleUnit, deg_to_rad, normalize_angle

log = logging.getLogger(__name__)

# Adapter 方法 -> PDF 原文路径（不做任何规范化）
PATHS = {
    "status": "/system/status",
    "info": "/system/info",
    "galileo": "/system/galileo_status",
    "speed": "/system/speed",
    "self_test": "/system/self_test",
    "config": "/system/config",
    "saved_maps": "/navigation/saved_maps",
    "current_map": "/navigation/current_map",
    "map_png": "/navigation/map_png",
    "pose": "/navigation/pose",
    "map_pose": "/map/pose",
    "current_path": "/navigation/current_path",
    "nav_points": "/navigation/nav_points",
    "path": "/navigation/path",
    "charge_pose": "/navigation/charge_pose",
    "loop_task": "/navigation/loop_task",
    "task": "/task",
    "action": "/action",
    # ONVIF 相机（PDF p42–48）
    "cameras": "/system/onvif_cameras",
    "camera_temperature": "/system/onvif_camera/temperature",
    "camera_snapshot": "/system/onvif_camera/snapshot",
    "camera_pose": "/system/onvif_camera/pose",
}


class HttpJcrobAdapter:
    mode = "http"

    # 能力声明（B 项）：全部 False = 逐点。真机确认支持节点内动作后再改这里。
    capabilities = {
        "supports_batch": False,
        "supports_inline_actions": False,
        "supports_pause": False,
        "cancel_semantics": "async",
    }

    def __init__(self, *, base_url: str, username: str, password: str,
                 token: str = "", timeout: float = 3.0,
                 angle_unit: AngleUnit = "auto") -> None:
        self.client = JcrobHttpClient(base_url, token=token, timeout=timeout)
        self.username = username
        self.password = password
        self.angle_unit: AngleUnit = angle_unit

    async def aclose(self) -> None:
        await self.client.aclose()

    async def ensure_token(self) -> None:
        if not self.client.token:
            await self.client.fetch_token(self.username, self.password)

    # ---- 只读接口 -------------------------------------------------------
    async def get_status(self) -> dict[str, Any]:
        return await self.client.get(PATHS["status"])

    async def get_info(self) -> dict[str, Any]:
        return await self.client.get(PATHS["info"])

    async def get_galileo(self) -> dict[str, Any]:
        raw = await self.client.get(PATHS["galileo"])
        return self._normalize_galileo(raw)

    async def get_speed(self) -> dict[str, Any]:
        return await self.client.get(PATHS["speed"])

    async def get_self_test(self) -> dict[str, Any]:
        return await self.client.get(PATHS["self_test"])

    # ---- ONVIF 相机（p42–48）：测温/抓拍/云台 ----
    async def get_camera_temperature(self) -> dict[str, Any]:
        """红外测温。返回 {max, min, avg, raw}；字段名按实际响应做兼容。"""
        raw = await self.client.get(PATHS["camera_temperature"])
        out: dict[str, Any] = {"raw": raw}
        if isinstance(raw, dict):
            for key in ("max", "maxTemp", "max_temperature", "highest"):
                if isinstance(raw.get(key), (int, float)):
                    out["max"] = float(raw[key])
                    break
            for key in ("min", "minTemp", "min_temperature", "lowest"):
                if isinstance(raw.get(key), (int, float)):
                    out["min"] = float(raw[key])
                    break
            for key in ("avg", "average", "avgTemp", "mean"):
                if isinstance(raw.get(key), (int, float)):
                    out["avg"] = float(raw[key])
                    break
            # 有的固件返回 points 列表：取最高温点
            pts = raw.get("points") or raw.get("data")
            if isinstance(pts, list) and pts:
                temps = [p.get("temp") for p in pts
                         if isinstance(p, dict) and isinstance(p.get("temp"), (int, float))]
                if temps and "max" not in out:
                    out["max"] = float(max(temps))
                    out["min"] = float(min(temps))
        return out

    async def camera_snapshot(self) -> bytes:
        """到点抓拍优先走 SDK（p46）。返回 JPEG 字节。"""
        res = await self.client.get(PATHS["camera_snapshot"])
        # 文档说"返回文件位置"：可能是路径/URL，也可能是 base64
        loc = ""
        if isinstance(res, dict):
            loc = str(res.get("path") or res.get("url") or res.get("file") or "")
        elif isinstance(res, str):
            loc = res
        if not loc:
            raise jerr.NotSupported("抓拍接口没返回文件位置")
        import base64

        if loc.startswith("data:image") and "," in loc:
            return base64.b64decode(loc.split(",", 1)[1])
        if loc.startswith("http"):
            return await self.client.get_bytes_url(loc)
        return await self.client.get_bytes_path(loc)

    async def get_config_view(self) -> dict[str, Any]:
        raw = await self.client.get(PATHS["config"])
        return project_config(raw)

    def _normalize_galileo(self, raw: dict[str, Any]) -> dict[str, Any]:
        """currentAngle 单位未标：只有 angle_unit 明确时才给 theta_rad。"""
        out = dict(raw)
        unit = self.angle_unit
        if unit == "auto":
            unit = "unknown"
        out["currentAngle_rad"] = normalize_angle(raw.get("currentAngle"), unit)
        out["angle_unit"] = unit
        return out

    async def get_pose(self) -> dict[str, Any]:
        """返回平台统一格式：x/y 米、theta_rad 弧度、angle_deg 原始度。"""
        try:
            raw = await self.client.get(PATHS["pose"])
        except jerr.JcrobError:
            raw = await self.client.get(PATHS["map_pose"])
        angle = raw.get("angle")
        theta = deg_to_rad(angle) if isinstance(angle, (int, float)) else None
        return {"x": raw.get("x"), "y": raw.get("y"),
                "angle_deg": angle, "theta_rad": theta, "raw": raw}

    async def list_maps(self) -> Any:
        return await self.client.get(PATHS["saved_maps"])

    async def get_current_map(self) -> dict[str, Any]:
        return await self.client.get(PATHS["current_map"])

    async def get_map_png(self, name: str) -> bytes:
        return await self.client.get_bytes(PATHS["map_png"], {"name": name})

    async def get_current_path(self) -> dict[str, Any]:
        return await self.client.get(PATHS["current_path"])

    async def get_nav_points(self, map_name: str = "", path_name: str = "") -> dict[str, Any]:
        params = {k: v for k, v in {"map_name": map_name, "path_name": path_name}.items() if v}
        return await self.client.get(PATHS["nav_points"], params or None)

    async def get_path(self, map_name: str = "", path_name: str = "") -> dict[str, Any]:
        params = {k: v for k, v in {"map_name": map_name, "path_name": path_name}.items() if v}
        return await self.client.get(PATHS["path"], params or None)

    async def get_charge_pose(self) -> dict[str, Any]:
        return await self.client.get(PATHS["charge_pose"])

    async def get_loop_task(self) -> Any:
        return await self.client.get(PATHS["loop_task"])

    async def get_tasks(self) -> Any:
        return await self.client.get(PATHS["task"])

    async def get_task(self, task_id: str) -> dict[str, Any]:
        return await self.client.get(PATHS["task"], {"id": task_id})

    async def get_actions(self) -> Any:
        return await self.client.get(PATHS["action"])

    async def probe_capabilities(self) -> dict[str, Any]:
        return await probe(self)


    # ---- 写操作：协议字段未确认，先明确拒绝（不假装支持） ----
    async def dispatch(self, order: dict) -> dict:
        """平台订单 → 真机 task JSON（sub_tasks: nav_action/image_action/sleep_action）。"""
        sub_tasks = []
        for a in order.get("actions") or []:
            params = {p.get("key"): p.get("value") for p in a.get("actionParameters", [])}
            action = a.get("actionType", "photo")
            if action in ("photo", "video", "thermal"):
                sub_tasks.append({"type": "image_action", "topic": "/camera_node/image_raw"})
            elif action == "wait":
                sub_tasks.append({"type": "sleep_action", "wait_time": int(params.get("sec") or 5)})
            else:
                sub_tasks.append({
                    "type": "nav_action",
                    "x": float(params.get("x") or 0),
                    "y": float(params.get("y") or 0),
                    "theta": float(params.get("yaw") or 0),
                })
        body = {"name": (order.get("orderId") or "platform-task")[:40],
                "loop_flag": bool(order.get("loop")), "sub_tasks": sub_tasks}
        res = await self.client.post(PATHS["task"], body)
        if isinstance(res, dict) and res.get("id"):
            return {"id": res["id"], "state": "RUNNING", "raw": res}
        if isinstance(res, list) and res:
            return {"id": res[0].get("id", ""), "state": "RUNNING", "raw": res[0]}
        return {"id": "", "state": "FAILED", "raw": res}

    async def capture(self, step=None, stream: str | None = None) -> dict:
        """到点抓拍：优先走 SDK 的 onvif_camera/snapshot（p46），失败再回落到 go2rtc 抓帧。"""
        from app.core.config import get_settings
        from app.services.snapshot import capture_frame, save_photo_bytes

        try:
            data = await self.camera_snapshot()
            if len(data) > 1024:
                return save_photo_bytes(data, source="sdk_snapshot")
        except Exception as exc:  # noqa: BLE001
            log.info("SDK 抓拍不可用（%s），回落到 go2rtc", exc.__class__.__name__)
        if not stream:
            raise RuntimeError("SDK 抓拍失败，且这台设备没有配置相机外设（camera）")
        return await asyncio.to_thread(capture_frame, stream, get_settings().go2rtc_base)

    async def pause(self) -> dict:
        raise jerr.NotSupported("JCROB 没有独立的暂停接口（只能取消任务）")

    async def resume(self) -> dict:
        raise jerr.NotSupported("JCROB 没有独立的继续接口")

    async def cancel(self) -> dict:
        try:
            return await self.client.post("/task/cancel", {})
        except jerr.JcrobError:
            # 退路：有些固件是 DELETE /task
            return await self.client.request("DELETE", PATHS["task"])

    async def get_order(self) -> dict:
        tasks = await self.get_tasks()
        if isinstance(tasks, list) and tasks:
            state = str(tasks[0].get("state", "")).upper()
            mapped = {"COMPLETE": "FINISHED", "FINISHED": "FINISHED",
                      "RUNNING": "RUNNING", "PAUSED": "PAUSED",
                      "CANCELLED": "FAILED", "ERROR": "FAILED"}.get(state, "RUNNING")
            return {"state": mapped, "raw": tasks[0]}
        # 列表为空 ≠ 任务完成（可能还没下发/已被清理）；返回 UNKNOWN 交给上层超时判定
        return {"state": "UNKNOWN"}
