"""为 X30 真机测试挑一个"附近可通行点"：读当前位姿 + 校验候选点是否在空闲栅格。"""

from __future__ import annotations

import math
import sys

sys.path.insert(0, r"D:\Desktop\防爆机器人\server")

from app.adapters.deeprobotics.protocol import X30Client  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.map_library import PlatformMap  # noqa: E402
from app.services.map_check import check_point_free  # noqa: E402

c = X30Client("192.168.1.106", 30000, timeout=4.0)
try:
    st = c.status()
finally:
    c.close()

x = float(st.get("PosX") or 0)
y = float(st.get("PosY") or 0)
print(f"当前位姿 x={x:.2f} y={y:.2f} yaw={st.get('AngleYaw')} location={st.get('Location')}")

with SessionLocal() as db:
    m = db.query(PlatformMap).filter(PlatformMap.is_active.is_(True)).first()
    print("激活地图:", m.name, m.width, "x", m.height, m.resolution, m.origin_x, m.origin_y)
    cands = []
    for dist in (1.0, 1.5, 2.0, 3.0):
        for deg in (0, 45, 90, 135, 180, 225, 270, 315):
            tx = x + dist * math.cos(math.radians(deg))
            ty = y + dist * math.sin(math.radians(deg))
            ok, why = check_point_free(db, m.id, tx, ty)
            if ok:
                cands.append((dist, deg, round(tx, 2), round(ty, 2), why or "空闲"))
    print(f"候选可通行点 {len(cands)} 个（前 12 个）：")
    for row in cands[:12]:
        print("  距离%.1fm 方向%3d° -> (%.2f, %.2f) %s" % row)
