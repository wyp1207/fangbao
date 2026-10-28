"""地图点位合法性校验：目标点必须在当前地图的有效栅格内。

为什么要有：客户点一下地图就派车过去，如果点在墙上/地图外，车会原地打转或报规划失败，
现场看起来就是"平台把车指挥傻了"。

栅格取值按 ROS map 约定：<50 障碍、>245 空闲、中间是未知。上传的地图不一定严格符合，
所以读不到像素时按"放行 + 警告"处理，不阻塞现场。
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.map_library import PlatformMap

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2] / "data" / "maps"


def current_map_id(db: Session, robot=None) -> int | None:
    """当前激活地图；优先按设备绑定的 robot_map_name 匹配，否则取 is_active。"""
    name = getattr(robot, "current_map_name", None) if robot is not None else None
    if name:
        row = db.query(PlatformMap).filter(PlatformMap.robot_map_name == name).first()
        if row is not None:
            return row.id
    row = db.query(PlatformMap).filter(PlatformMap.is_active.is_(True)).first()
    if row is not None:
        return row.id
    row = db.query(PlatformMap).order_by(PlatformMap.id).first()
    return row.id if row else None


def check_point_free(db: Session, map_id: int | None, x: float, y: float) -> tuple[bool, str]:
    """返回 (是否可去, 原因)。点在地图外/障碍 → False；未知区 → 放行但提示。"""
    if map_id is None:
        return True, "没有地图信息，跳过校验"
    m = db.get(PlatformMap, map_id)
    if m is None:
        return True, "地图不存在，跳过校验"

    res = float(m.resolution or 0.05)
    ox = float(m.origin_x or 0)
    oy = float(m.origin_y or 0)
    w, h = int(m.width or 0), int(m.height or 0)
    if w <= 0 or h <= 0:
        return True, "地图尺寸未知，跳过校验"

    in_x = ox <= x <= ox + w * res
    in_y = oy <= y <= oy + h * res
    if not in_x or not in_y:
        return False, f"超出地图范围（x∈[{ox:.1f},{ox + w * res:.1f}]，"\
                      f"y∈[{oy:.1f},{oy + h * res:.1f}]）"

    col = int((x - ox) / res)
    row = int(h - 1 - (y - oy) / res)
    col = max(0, min(w - 1, col))
    row = max(0, min(h - 1, row))

    path = ROOT / (m.image_path or "")
    if not path.exists():
        return True, "地图文件缺失，跳过栅格校验"
    try:
        from PIL import Image

        with Image.open(path) as img:
            gray = img.convert("L")
            val = gray.getpixel((col, row))
    except Exception:  # noqa: BLE001
        log.warning("地图栅格读取失败 map=%s", map_id, exc_info=True)
        return True, "地图读取失败，跳过栅格校验"

    if val < 50:
        return False, "目标点在障碍物/墙体上"
    if val < 200:
        return True, "目标点位于未探索区域，机器人可能规划失败，请现场确认"
    return True, ""
