"""导入 X30「jueying」真实栅格图到本机平台地图库（幂等）。

背景：机器人只认自己 SLAM 建出来的图；平台地图库要能预览任意一张图。
本脚本把 PGM（或已有 PNG）转成平台用的 L 模式 PNG，再按 PlatformMap 模型
写入 platform_map 表，供 3D 页面 `?map=<id>` 直接预览。

用法：
    python scripts/import_jueying_map.py                       # 默认用桌面上的 jueying.pgm
    python scripts/import_jueying_map.py --source-png <path>   # 改用平台已存的 1051×1351 当前图
    python scripts/import_jueying_map.py --expect 402x287      # 明确按小图导入

约定：
- 图片尺寸永远以实际图片为准。与 --expect 不符时脚本默认拒绝写库，
  避免“图是 402×287、库里写 1051×1351”这种坐标错位（点位会整体偏）。
- is_active 只在新建时写 False；同名已存在时原样复用、绝不改激活状态，
  不会动首页当前地图。
- 改库前用 sqlite3 的 backup API 备份到 server/data/app.db.bak-<时间戳>。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
sys.path.insert(0, str(SERVER))

from PIL import Image  # noqa: E402

DEFAULT_PGM = Path(r"D:\Desktop\工作1\机器狗\jueying建图test\jueying.pgm")
DEFAULT_OUT = SERVER / "data" / "maps" / "jueying_demo.png"


def parse_size(text: str) -> tuple[int, int]:
    w, h = text.lower().split("x", 1)
    return int(w), int(h)


def backup_db(db_path: Path) -> Path:
    """用 sqlite3 的在线备份 API 复制数据库（WAL 下也安全）。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = db_path.with_name(f"{db_path.name}.bak-{stamp}")
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(bak))
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    return bak


def main() -> int:
    ap = argparse.ArgumentParser(description="导入 jueying 真实栅格图到平台地图库（幂等）")
    ap.add_argument("--pgm", type=Path, default=DEFAULT_PGM, help="PGM 源文件（默认桌面 jueying.pgm）")
    ap.add_argument("--source-png", type=Path, default=None,
                    help="改用一张已有 PNG 作源（例如平台已从 X30 拉取的 1051×1351 当前图）")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出的 L 模式 PNG")
    ap.add_argument("--name", default="X30场站-jueying实图")
    ap.add_argument("--floor", default="1F")
    ap.add_argument("--station", default="X30场地")
    ap.add_argument("--resolution", type=float, default=0.1)
    ap.add_argument("--origin-x", type=float, default=-57.9)
    ap.add_argument("--origin-y", type=float, default=-53.0)
    ap.add_argument("--origin-theta", type=float, default=0.0)
    ap.add_argument("--robot-map-name", default="jueying")
    ap.add_argument("--expect", default="1051x1351",
                    help="期望尺寸 WxH；实际不符时默认拒绝写库（--force 可跳过）")
    ap.add_argument("--force", action="store_true", help="尺寸不符也照样导入（元数据仍用实际尺寸）")
    args = ap.parse_args()

    source: Path = args.source_png if args.source_png else args.pgm
    if not source.exists():
        print(f"[ERR] 源图不存在：{source}")
        return 2

    # 1) 转 L 模式 PNG（PGM 和 PNG 都走同一条路）
    img = Image.open(source)
    mode_in = img.mode
    img = img.convert("L")
    w, h = img.size
    args.out.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out, format="PNG")
    print(f"[1/3] {source.name} ({mode_in}) -> {args.out}  尺寸 {w}×{h} px")

    # 2) 尺寸守卫：元数据必须和真实图片一致，否则点位会整体错位
    expected = parse_size(args.expect)
    if (w, h) != expected and not args.force:
        print(f"[ERR] 尺寸不符：图片实际 {w}×{h}，期望 {expected[0]}×{expected[1]}。")
        print("      这不一定是脚本的问题：源图可能不是你要的那张。")
        print("      确认要用这张图，就显式加 --expect {0}x{1}（或 --force）。".format(w, h))
        return 3
    if (w, h) != expected:
        print(f"[WARN] 尺寸不符但 --force 已指定：按实际 {w}×{h} 写入平台库")

    # 3) 改库前备份，然后幂等 upsert
    from app.core.config import SERVER_ROOT, get_settings
    from app.db.session import Base, SessionLocal, engine
    from app.models.map_library import PlatformMap

    db_url = get_settings().db_url
    if not db_url.startswith("sqlite:///"):
        print(f"[ERR] 当前不是本机 SQLite（JC_DB_URL={db_url}），本脚本只做本机导入")
        return 4
    db_path = Path(db_url.split("///", 1)[-1])
    if not db_path.is_absolute():
        db_path = SERVER_ROOT / db_path
    bak = backup_db(db_path)
    print(f"[2/3] 已备份数据库：{bak}")

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        row = db.query(PlatformMap).filter(PlatformMap.name == args.name).first()
        reused = row is not None
        if row is None:
            row = PlatformMap(name=args.name, is_active=False)
            db.add(row)
        row.floor = args.floor
        row.station = args.station
        row.resolution = args.resolution
        row.origin_x = args.origin_x
        row.origin_y = args.origin_y
        row.origin_theta = args.origin_theta
        row.image_path = args.out.name
        row.width = w
        row.height = h
        row.robot_map_name = args.robot_map_name
        row.note = f"本地导入 {source.name}（{w}×{h} @ {args.resolution}m/px, origin {args.origin_x},{args.origin_y}）"
        db.commit()
        db.refresh(row)
        state = "复用已存在记录" if reused else "新建记录"
        print(f"[3/3] {state}：map id={row.id}  {row.name}")
        print(f"      {row.width}×{row.height} @ {row.resolution}m/px  "
              f"origin=({row.origin_x},{row.origin_y},{row.origin_theta})  "
              f"image={row.image_path}  is_active={row.is_active}")

    # 只读校验：确认没动别的地图的 is_active
    with SessionLocal() as db:
        actives = [m.name for m in db.query(PlatformMap).filter(PlatformMap.is_active.is_(True)).all()]
        print(f"      当前激活地图（未改动）：{actives}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
