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
    """生成一张"像楼层平面图"的占位底图：浅灰自由区 + 深灰墙体 + 几个房间。

    尺寸必须与 saved_maps 里的 width/height 一致——真机也是拿 PNG 像素尺寸
    和 resolution/origin 配对算坐标，尺寸不对，点位会全落到图外。
    纯网格太像草稿纸，画上墙体和房间，大屏才像一张真地图。
    """
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    free, wall, room = (246, 248, 252), (58, 70, 88), (228, 233, 241)
    px = [[free for _ in range(width)] for _ in range(height)]

    def rect(x0: int, y0: int, x1: int, y1: int, color, fill=False) -> None:
        for y in range(max(0, y0), min(height, y1)):
            for x in range(max(0, x0), min(width, x1)):
                if fill or y in (y0, y1 - 1) or x in (x0, x1 - 1):
                    px[y][x] = color

    # 外墙
    rect(6, 6, width - 6, height - 6, wall)
    # 房间：左上一间、右上两间、下方大厅
    rect(20, 20, 130, 110, wall)
    rect(150, 20, 210, 110, wall)
    rect(220, 20, 285, 150, wall)
    rect(20, 150, 285, 150, wall, fill=True)      # 走廊隔墙
    rect(20, 200, 120, 300, wall)
    rect(160, 200, 285, 300, wall)
    # 门洞：把墙打断，看起来像真的平面图
    for y in range(140, 165):
        for x in range(140, 175):
            px[y][x] = free
    for y in range(200, 240):
        for x in range(125, 155):
            px[y][x] = free
    # 房间地面稍微压深一点
    for y0, x0, y1, x1 in ((22, 22, 108, 128), (152, 22, 108, 208),
                           (222, 22, 148, 283), (22, 202, 298, 118), (162, 202, 298, 283)):
        for y in range(y0, y1):
            for x in range(x0, x1):
                if px[y][x] == free:
                    px[y][x] = room

    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row += bytes(px[y][x])
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

    # ---- 写操作：mock 里模拟一个状态机，等真机联调时换成 HTTP 调用 ----
    async def dispatch(self, order: dict) -> dict:
        self._order = {"id": f"MOCK-{int(time.time())}", "state": "RUNNING",
                       "progress": 0, "order": order}
        return dict(self._order)

    async def pause(self) -> dict:
        if getattr(self, "_order", None):
            self._order["state"] = "PAUSED"
        return dict(getattr(self, "_order", {}) or {})

    async def resume(self) -> dict:
        if getattr(self, "_order", None):
            self._order["state"] = "RUNNING"
        return dict(getattr(self, "_order", {}) or {})

    async def cancel(self) -> dict:
        if getattr(self, "_order", None):
            self._order["state"] = "FINISHED"
        return dict(getattr(self, "_order", {}) or {})

    async def get_order(self) -> dict:
        order = getattr(self, "_order", None) or {}
        # 模拟"走了一会儿才到"：前两次查询仍是执行中，第三次到点
        if order.get("state") == "RUNNING":
            order["polls"] = order.get("polls", 0) + 1
            if order["polls"] >= 2:
                order["state"] = "FINISHED"
        return dict(order)

    async def goto(self, x: float, y: float, yaw: float = 0.0) -> dict:
        self._order = {"id": f"MOCK-{int(time.time())}", "state": "RUNNING",
                       "polls": 0, "target": {"x": x, "y": y, "yaw": yaw}}
        return dict(self._order)

    async def get_actions(self) -> Any:
        return self._load("action")

    async def probe_capabilities(self) -> dict[str, Any]:
        return await probe(self)
