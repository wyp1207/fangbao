"""平台地图库：导入 / 查看 / 标定 / 点位草稿。

能先做的（不需要真机）：
- 上传 PNG 台账图，人工填比例尺与原点
- 平台侧点位草稿（点击地图生成），标「待同步」
- 与机器人地图名建立映射（robot_map_name），等真机后核对

必须等真机的：
- 把地图下发给机器人并让其生效
- 把草稿点位写进机器人 nav_points
这两条接口返回 501 并说明原因，不做假成功。
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_csrf, require_roles
from app.core.errors import BadRequest, NotFound
from app.db.session import get_db
from app.models.map_library import PlatformMap, PointDraft
from app.models.user import User
from app.services.messages import audit, store as msg_store

router = APIRouter(prefix="/maps/library", tags=["map-library"])

ROOT = Path(__file__).resolve().parents[3] / "data" / "maps"
MAX_BYTES = 20 * 1024 * 1024


def _out(m: PlatformMap) -> dict:
    return {
        "id": m.id, "name": m.name, "floor": m.floor, "station": m.station,
        "resolution": m.resolution,
        "origin": [m.origin_x, m.origin_y, m.origin_theta],
        "width": m.width, "height": m.height,
        "robot_map_name": m.robot_map_name, "is_active": m.is_active,
        "note": m.note,
        "created_at": m.created_at.isoformat(timespec="seconds") if m.created_at else None,
        "image_url": f"/api/v1/maps/library/{m.id}/image",
        "draft_points": 0,
    }


@router.get("")
def list_library(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[dict]:
    rows = db.query(PlatformMap).order_by(PlatformMap.id.desc()).all()
    counts = {}
    for p in db.query(PointDraft).all():
        counts[p.map_id] = counts.get(p.map_id, 0) + 1
    out = []
    for m in rows:
        d = _out(m)
        d["draft_points"] = counts.get(m.id, 0)
        out.append(d)
    return out


@router.post("", dependencies=[Depends(require_csrf)])
async def import_map(
    file: UploadFile = File(...),
    name: str = Form(...),
    floor: str = Form("1F"),
    station: str = Form("默认场站"),
    resolution: float = Form(0.05),
    origin_x: float = Form(0.0),
    origin_y: float = Form(0.0),
    origin_theta: float = Form(0.0),
    robot_map_name: str = Form(""),
    note: str = Form(""),
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    # 分辨率填错会直接导致点位坐标错位——这是能撞设备的事，必须在入口拦
    if not (0.01 <= resolution <= 0.5):
        raise BadRequest(
            f"分辨率 {resolution} 不合理：应在 0.01–0.50 米/像素之间（0.05 是常见激光雷达栅格）",
            code="BAD_RESOLUTION",
        )
    for label, value in (("原点 X", origin_x), ("原点 Y", origin_y)):
        if abs(value) > 5000:
            raise BadRequest(f"{label}={value} 超出合理范围（±5000 米）", code="BAD_ORIGIN")

    if file.content_type not in ("image/png", "image/jpeg"):
        raise BadRequest("只接受 PNG / JPG", code="BAD_MIME")
    raw = await file.read()
    if len(raw) > MAX_BYTES:
        raise BadRequest("文件超过 20MB", code="TOO_LARGE")

    from PIL import Image

    try:
        img = Image.open(io.BytesIO(raw))
        w, h = img.size
    except Exception as exc:  # noqa: BLE001
        raise BadRequest(f"图片解析失败：{exc}", code="BAD_IMAGE") from exc

    ROOT.mkdir(parents=True, exist_ok=True)
    fname = f"{uuid.uuid4().hex}.png"
    target = ROOT / fname
    img.convert("RGB").save(target, format="PNG")

    m = PlatformMap(
        name=name, floor=floor, station=station, resolution=resolution,
        origin_x=origin_x, origin_y=origin_y, origin_theta=origin_theta,
        image_path=fname, width=w, height=h,
        robot_map_name=robot_map_name or None, note=note or None,
    )
    db.add(m)
    db.commit()
    db.refresh(m)

    audit(db=db, action="map.import", target=name, user=me,
          detail={"file": fname, "size": [w, h], "resolution": resolution})
    msg_store.add("info", "system", f"导入地图：{name}",
                  f"{w}×{h} 像素 · 比例尺 {resolution} 米/像素", {"to": "map"})
    return _out(m)


@router.get("/{map_id}/image")
def get_image(map_id: int, db: Session = Depends(get_db)) -> FileResponse:
    m = db.get(PlatformMap, map_id)
    if not m:
        raise NotFound("地图不存在")
    path = ROOT / m.image_path
    if not path.exists():
        raise NotFound("地图文件丢失")
    return FileResponse(path, media_type="image/png")


@router.patch("/{map_id}", dependencies=[Depends(require_csrf)])
def update_map(
    map_id: int, body: dict,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    m = db.get(PlatformMap, map_id)
    if not m:
        raise NotFound("地图不存在")
    for k in ("name", "floor", "station", "resolution", "origin_x", "origin_y",
              "origin_theta", "robot_map_name", "note", "is_active"):
        if k in body and body[k] is not None:
            setattr(m, k, body[k])
    db.commit()
    db.refresh(m)
    audit(db=db, action="map.update", target=m.name, user=me, detail=body)
    return _out(m)


@router.delete("/{map_id}", dependencies=[Depends(require_csrf)])
def delete_map(
    map_id: int, db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin")),
) -> dict:
    m = db.get(PlatformMap, map_id)
    if not m:
        raise NotFound("地图不存在")
    db.query(PointDraft).filter(PointDraft.map_id == map_id).delete()
    db.delete(m)
    db.commit()
    (ROOT / m.image_path).unlink(missing_ok=True)
    audit(db=db, action="map.delete", target=m.name, user=me)
    return {"ok": True}


# ---------------- 点位草稿 ----------------

class PointIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    x: float
    y: float
    theta: float = 0.0
    note: str | None = None


@router.get("/{map_id}/points")
def list_points(map_id: int, db: Session = Depends(get_db),
                _: User = Depends(get_current_user)) -> list[dict]:
    rows = db.query(PointDraft).filter(PointDraft.map_id == map_id).order_by(PointDraft.id).all()
    return [
        {"id": r.id, "name": r.name, "x": r.x, "y": r.y, "theta": r.theta,
         "note": r.note, "synced": r.synced}
        for r in rows
    ]


@router.post("/{map_id}/points", dependencies=[Depends(require_csrf)])
def add_point(
    map_id: int, body: PointIn,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    map_row = db.get(PlatformMap, map_id)
    if not map_row:
        raise NotFound("地图不存在")

    # 点位必须落在这张图覆盖的物理范围内，否则下发后机器人会往图外走
    if map_row.width and map_row.height:
        px = (body.x - map_row.origin_x) / map_row.resolution
        py = (body.y - map_row.origin_y) / map_row.resolution
        if not (0 <= px <= map_row.width and 0 <= py <= map_row.height):
            raise BadRequest(
                f"点位 ({body.x}, {body.y}) 不在这张图范围内："
                f"图幅 {map_row.width}×{map_row.height} px，"
                f"对应 X {map_row.origin_x:.1f}~{map_row.origin_x + map_row.width * map_row.resolution:.1f} m，"
                f"Y {map_row.origin_y:.1f}~{map_row.origin_y + map_row.height * map_row.resolution:.1f} m",
                code="POINT_OUT_OF_MAP",
            )

    p = PointDraft(map_id=map_id, name=body.name, x=body.x, y=body.y,
                   theta=body.theta, note=body.note)
    db.add(p)
    db.commit()
    db.refresh(p)
    audit(db=db, action="point.draft", target=f"{body.name} @map{map_id}", user=me,
          detail={"x": body.x, "y": body.y})
    return {"id": p.id, "name": p.name, "x": p.x, "y": p.y, "synced": p.synced}


@router.post("/{map_id}/points/import", dependencies=[Depends(require_csrf)])
def import_points(
    map_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    """CSV 批量导入点位草稿。

    表头：name,x,y,theta,note（name/x/y 必填，theta 默认 0）。
    同名点位视为更新，不会重复插入；单行出错不影响其他行。
    """
    import csv

    map_row = db.get(PlatformMap, map_id)
    if not map_row:
        raise NotFound("地图不存在")

    raw = file.file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("gbk", "replace")

    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise BadRequest("CSV 是空的", code="EMPTY_CSV")

    existing = {p.name: p for p in db.query(PointDraft).filter(PointDraft.map_id == map_id).all()}
    created = updated = 0
    errors: list[str] = []

    for i, row in enumerate(rows, start=2):
        name = (row.get("name") or "").strip()
        if not name:
            errors.append(f"第 {i} 行：缺 name")
            continue
        try:
            x = float(row.get("x") or "")
            y = float(row.get("y") or "")
        except ValueError:
            errors.append(f"第 {i} 行（{name}）：x/y 不是数字")
            continue
        theta = 0.0
        if (row.get("theta") or "").strip():
            try:
                theta = float(row["theta"])
            except ValueError:
                errors.append(f"第 {i} 行（{name}）：theta 不是数字，按 0 处理")

        px = (x - map_row.origin_x) / (map_row.resolution or 0.05)
        py = (y - map_row.origin_y) / (map_row.resolution or 0.05)
        if map_row.width and map_row.height and not (0 <= px <= map_row.width and 0 <= py <= map_row.height):
            errors.append(f"第 {i} 行（{name}）：坐标 ({x}, {y}) 不在地图范围内")
            continue

        if name in existing:
            p = existing[name]
            p.x, p.y, p.theta = x, y, theta
            p.note = row.get("note") or p.note
            updated += 1
        else:
            p = PointDraft(map_id=map_id, name=name, x=x, y=y, theta=theta,
                           note=row.get("note") or None)
            db.add(p)
            existing[name] = p
            created += 1

    db.commit()
    audit(db=db, action="point.import", target=f"map{map_id}", user=me,
          detail={"created": created, "updated": updated, "errors": len(errors)})
    return {"created": created, "updated": updated, "errors": errors[:20],
            "total": created + updated}


@router.get("/{map_id}/points/export")
def export_points(map_id: int, db: Session = Depends(get_db),
                  _: User = Depends(get_current_user)):
    """导出点位 CSV（含模板列），可直接拿去改完再导入。"""
    import csv

    if not db.get(PlatformMap, map_id):
        raise NotFound("地图不存在")
    rows = db.query(PointDraft).filter(PointDraft.map_id == map_id).order_by(PointDraft.id).all()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "x", "y", "theta", "note"])
    for r in rows:
        w.writerow([r.name, r.x, r.y, r.theta, r.note or ""])

    from fastapi.responses import Response

    return Response(
        content=buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="points_map{map_id}.csv"'},
    )


@router.delete("/points/{point_id}", dependencies=[Depends(require_csrf)])
def delete_point(point_id: int, db: Session = Depends(get_db),
                 me: User = Depends(require_roles("admin", "operator"))) -> dict:
    p = db.get(PointDraft, point_id)
    if not p:
        raise NotFound("点位不存在")
    db.delete(p)
    db.commit()
    audit(db=db, action="point.delete", target=p.name, user=me)
    return {"ok": True}


@router.post("/points/{point_id}/sync", dependencies=[Depends(require_csrf)])
def sync_point(point_id: int, db: Session = Depends(get_db),
               _: User = Depends(require_roles("admin"))) -> dict:
    """同步到机器人：真机联调后开放。现在明确拒绝，不假装成功。"""
    from fastapi import HTTPException

    raise HTTPException(
        status_code=501,
        detail="点位下发需要机器人写权限：等真机到场联调 + 现场授权签字后开放",
    )
