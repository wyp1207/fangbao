"""通过 SFTP 拉取 X30 当前地图（jueying.pgm/jueying.yaml）并导入平台地图库。

只读：仅下载文件，不改机器人。地图：1051x1351 @0.1m/px，origin(-57.9,-53.0)。
"""

from __future__ import annotations

import io
import sys
import uuid
from pathlib import Path

import paramiko

sys.path.insert(0, r"D:\Desktop\防爆机器人\server")

from app.db.session import SessionLocal  # noqa: E402
from app.models.map_library import PlatformMap  # noqa: E402

MAPS = Path(r"D:\Desktop\防爆机器人\server\data\maps")
MAPS.mkdir(parents=True, exist_ok=True)

HOST, USER, PWD = "192.168.1.106", "ysc", "'"
REMOTE_DIR = "/home/ysc/jy_cog/system/map"


def main() -> int:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PWD, timeout=10)
    sftp = c.open_sftp()
    try:
        yaml_text = sftp.open(f"{REMOTE_DIR}/jueying.yaml").read().decode()
        print("yaml:", yaml_text.strip().replace("\n", " | "))
        with sftp.open(f"{REMOTE_DIR}/jueying.pgm", "rb") as f:
            pgm = f.read()
        print("pgm bytes:", len(pgm))
    finally:
        sftp.close()
        c.close()

    from PIL import Image

    img = Image.open(io.BytesIO(pgm))
    w, h = img.size
    png = MAPS / f"{uuid.uuid4().hex}.png"
    img.convert("L").save(png)
    print("converted:", png.name, w, "x", h)

    # 解析 yaml
    res, ox, oy = 0.1, 0.0, 0.0
    for line in yaml_text.splitlines():
        if line.startswith("resolution:"):
            res = float(line.split(":")[1])
        if line.startswith("origin:"):
            parts = line.split(":", 1)[1].strip().strip("[]").split(",")
            ox, oy = float(parts[0]), float(parts[1])

    with SessionLocal() as db:
        name = "X30场站-当前图"
        row = db.query(PlatformMap).filter(PlatformMap.name == name).first()
        if row is None:
            row = PlatformMap(name=name, floor="1F", station="X30场地",
                              resolution=res, origin_x=ox, origin_y=oy, origin_theta=0.0,
                              image_path=png.name, width=w, height=h,
                              robot_map_name="jueying", is_active=True,
                              note="SFTP 从 X30 导航主机拉取（jueying.pgm，2026-07-21）")
            db.add(row)
            db.commit()
            db.refresh(row)
        else:
            row.resolution, row.origin_x, row.origin_y = res, ox, oy
            row.image_path, row.width, row.height = png.name, w, h
            row.is_active = True
            db.commit()
        db.query(PlatformMap).filter(PlatformMap.id != row.id).update({"is_active": False})
        db.commit()
        print(f"平台地图 id={row.id} {row.width}x{row.height} @{row.resolution} "
              f"origin=({row.origin_x},{row.origin_y})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
