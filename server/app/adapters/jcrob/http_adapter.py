"""真机 HTTP Adapter（只读部分）。

写操作（任务下发/充电/IO/遥控）本期不实现；CommandGateway 在 services/ 里留了闸门骨架，
等 11/10 真机联调、采集表第 15–17 行签字后再开。
"""

from __future__ import annotations

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
}


class HttpJcrobAdapter:
    mode = "http"

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
