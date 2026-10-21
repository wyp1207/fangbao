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


def _make_png(width: int, height: int) -> bytes:
    """生成占位底图：暗底 + 每 50px 一条网格线。

    尺寸必须与 saved_maps 里的 width/height 一致——真机也是拿 PNG 像素尺寸
    和 resolution/origin 配对算坐标的，尺寸不对，点位会全落到图外。
    """
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    bg, grid = (12, 22, 34), (30, 49, 72)
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row += bytes(grid if (x % 50 == 0 or y % 50 == 0) else bg)
        rows.append(b"\x00" + bytes(row))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 6)) + chunk(b"IEND", b""))


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
        # 尺寸跟 saved_maps 一致，否则坐标换算会和底图对不上
        for meta in await self.list_maps():
            if meta.get("name") == name:
                return _make_png(int(meta.get("width", 306)), int(meta.get("height", 324)))
        raise jerr.NotSupported(f"mock 里没有地图 {name}")

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
