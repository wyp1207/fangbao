"""把 8890 老平台的 X30 真实场站地图导入本平台（幂等）。

来源：http://192.168.8.40:8890/assets/map.png
元数据（老平台 /api/patrol/map）：402x287，resolution 0.1，origin (-20.7, -10.7)
"""

from __future__ import annotations

import io
import sys
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, r"D:\Desktop\防爆机器人\server")

from app.db.session import Base, SessionLocal, engine  # noqa: E402
from app.models.map_library import PlatformMap  # noqa: E402

ROOT = Path(r"D:\Desktop\防爆机器人\server")
MAPS = ROOT / "data" / "maps"


def main() -> int:
    Base.metadata.create_all(bind=engine)
    MAPS.mkdir(parents=True, exist_ok=True)

    url = "http://192.168.8.40:8890/assets/map.png"
    req = urllib.request.Request(url, headers={"User-Agent": "jcrob-import"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = r.read()
    print("下载地图:", len(data), "bytes")

    name = "X30场站-1F"
    with SessionLocal() as db:
        row = db.query(PlatformMap).filter(PlatformMap.name == name).first()
        if row is None:
            fname = f"{uuid.uuid4().hex}.png"
            (MAPS / fname).write_bytes(data)
            row = PlatformMap(
                name=name, floor="1F", station="X30场地",
                resolution=0.1, origin_x=-20.7, origin_y=-10.7, origin_theta=0.0,
                image_path=fname, width=402, height=287,
                robot_map_name="map1", is_active=True,
                note="从 8890 老平台导入；X30 现场地图（402x287 @0.1m/px, origin -20.7,-10.7）",
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            print("已导入地图 id=", row.id, "file=", fname)
        else:
            print("地图已存在 id=", row.id, "（不重复导入）")

        # 把其它地图设为非激活，只留这张
        db.query(PlatformMap).filter(PlatformMap.id != row.id).update({"is_active": False})
        db.commit()
        print("激活地图：", row.name, row.width, "x", row.height, row.resolution, row.origin_x, row.origin_y)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
