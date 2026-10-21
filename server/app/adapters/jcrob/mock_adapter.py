"""Mock Adapter：没有真机时用 PDF 示例数据驱动前端与测试。

fixtures 取自 PDF 原文示例（p55 地图参数、p61 saved_maps、p72 nav_points、
p107 环境字段），不是编造的字段。11/10 真机数据回来后，用探针录包替换同名文件即可。
"""

from __future__ import annotations

import json
import math
import struct
import time
import zlib
from pathlib import Path
from typing import Any

from app.adapters.jcrob import errors as jerr
from app.adapters.jcrob.capability import probe
from app.adapters.jcrob.config_view import project_config


def _make_png(size: int = 64) -> bytes:
    """纯色占位底图（不引 Pillow）。真机联调时用 /navigation/map_png 替换。"""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + bytes([11, 22, 32] * size) for _ in range(size))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


_PNG_1PX = _make_png()


class MockJcrobAdapter:
    mode = "mock"

    def __init__(self, fixtures_dir: str | Path, *, angle_unit: str = "auto") -> None:
        self.dir = Path(fixtures_dir)
        self.angle_unit = angle_unit
        self._t0 = time.monotonic()

    async def aclose(self) -> None:
        return None

    def _load(self, name: str) -> Any:
        path = self.dir / f"{name}.json"
        if not path.exists():
            raise jerr.NotSupported(f"mock fixture 缺失: {path.name}")
        return json.loads(path.read_text(encoding="utf-8"))

    # ---- 动态部分：让驾驶舱动起来 ---------------------------------------
    def _sim_pose(self) -> dict[str, float]:
        t = time.monotonic() - self._t0
        cx, cy, r = 0.0, -2.0, 3.0
        x = cx + r * math.cos(t / 20.0)
        y = cy + r * math.sin(t / 20.0)
        heading = math.degrees((t / 20.0) + math.pi / 2)
        return {"x": round(x, 3), "y": round(y, 3), "angle": round(heading % 360, 3)}

    async def get_pose(self) -> dict[str, Any]:
        p = self._sim_pose()
        return {"x": p["x"], "y": p["y"], "angle_deg": p["angle"],
                "theta_rad": math.radians(p["angle"]), "raw": dict(p)}

    async def get_status(self) -> dict[str, Any]:
        return self._load("system_status")

    async def get_info(self) -> dict[str, Any]:
        return self._load("system_info")

    async def get_galileo(self) -> dict[str, Any]:
        raw = dict(self._load("galileo_status"))
        p = self._sim_pose()
        raw.update(currentPosX=p["x"], currentPosY=p["y"],
                   currentAngle=p["angle"], currentSpeedX=0.4,
                   currentSpeedTheta=0.05)
        raw["currentAngle_rad"] = math.radians(p["angle"]) if self.angle_unit in ("deg", "auto") else raw["currentAngle"]
        raw["angle_unit"] = "deg" if self.angle_unit in ("deg", "auto") else self.angle_unit
        return raw

    async def get_speed(self) -> dict[str, Any]:
        return {"speed_x": 0.4, "speed_y": 0.0, "speed_angle": 0.05}

    async def get_self_test(self) -> dict[str, Any]:
        return self._load("self_test")

    async def get_config_view(self) -> dict[str, Any]:
        return project_config(self._load("config"))

    async def list_maps(self) -> Any:
        return self._load("saved_maps")

    async def get_current_map(self) -> dict[str, Any]:
        return self._load("current_map")

    async def get_map_png(self, name: str) -> bytes:
        return _PNG_1PX

    async def get_current_path(self) -> dict[str, Any]:
        return self._load("current_path")

    async def get_nav_points(self, map_name: str = "", path_name: str = "") -> dict[str, Any]:
        return self._load("nav_points")

    async def get_path(self, map_name: str = "", path_name: str = "") -> dict[str, Any]:
        return self._load("path")

    async def get_charge_pose(self) -> dict[str, Any]:
        return self._load("charge_pose")

    async def get_loop_task(self) -> Any:
        return self._load("loop_task")

    async def get_tasks(self) -> Any:
        return self._load("task")

    async def get_task(self, task_id: str) -> dict[str, Any]:
        for task in self._load("task"):
            if task.get("id") == task_id:
                return task
        raise jerr.NotSupported(f"mock 里没有任务 {task_id}")

    async def get_actions(self) -> Any:
        return self._load("action")

    async def probe_capabilities(self) -> dict[str, Any]:
        return await probe(self)
