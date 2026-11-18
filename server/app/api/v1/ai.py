"""AI 识别结果接入。

PPT 的六类算法我们不做算法本体，但必须能把算法服务的结果接进来：
算法盒每推一条结果 → 落库（原图存盘）→ 超阈值就生成告警 → 告警可回看原图。

认证：优先 X-Api-Key（scope=ai:write），也允许登录用户手工补录。
幂等：(camera_id, algorithm, ts) 唯一，算法服务重试不会刷出两条。
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.services.api_auth import require_scope, session_or_key
from app.core.errors import BadRequest, NotFound, PlatformError
from app.db.session import get_db
from app.models.ai import AiAlgorithm, AiPresetRule, AiResult, AiStream
from app.models.alarm import AlarmRecord
from app.models.user import User

router = APIRouter(prefix="/ai", tags=["ai"])

ROOT = Path(__file__).resolve().parents[3] / "data" / "ai_images"

# 演示数据在 ai_result 里靠 source_id 区分：99 是本机演示种子，不是真实回调。
# 页面要给出“演示数据”角标，接口必须能一眼看出哪些行是演示、有多少条。
DEMO_SOURCE_ID = 99

DEFAULT_ALGORITHMS = [
    ("meter", "表计读数", "device", "MPa"),
    ("defect", "设备缺陷", "device", None),
    ("thermal", "红外测温", "device", "℃"),
    ("gas", "气体泄漏", "env", "%LEL"),
    ("smoke", "烟火识别", "env", None),
    ("helmet", "未戴安全帽", "person", None),
    ("intrusion", "区域入侵", "safety", None),
    ("fire_extinguisher", "灭火器缺失", "safety", None),
]


class ResultIn(BaseModel):
    algorithm: str = Field(min_length=1, max_length=48)
    camera_id: int | None = None
    point_id: int | None = None
    value: float | None = None
    text: str | None = None
    confidence: float = 0.0
    ts: datetime | None = None
    image_base64: str | None = None      # 兼容算法盒直接推图
    image_url: str | None = None         # 或给一个可下载/可回看的地址
    boxes: list[dict] = Field(default_factory=list)


def _save_image(b64: str) -> str:
    ROOT.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y%m%d")
    (ROOT / day).mkdir(exist_ok=True)
    raw = b64.split(",", 1)[-1]
    data = base64.b64decode(raw, validate=False)
    if len(data) > 8 * 1024 * 1024:
        raise BadRequest("图片超过 8MB", code="IMAGE_TOO_LARGE")
    name = f"{day}/{uuid.uuid4().hex}.jpg"
    (ROOT / name).write_bytes(data)
    return f"ai_images/{name}"


def _out(r: AiResult, algorithm_name: str | None = None,
         alarm_level: str | None = None) -> dict:
    return {
        "id": r.id, "algorithm": r.algorithm, "algorithm_name": algorithm_name or r.algorithm,
        "camera_id": r.camera_id, "point_id": r.point_id,
        # 真实回调（.170）的盒子侧标识：平台相机台账还没映射，先原样给前端看
        "external_camera_id": r.external_camera_id,
        "camera_name": r.external_camera_name,
        "external_algorithm_id": r.external_algorithm_id,
        "value": r.value, "text": r.text, "confidence": r.confidence,
        "image": f"/api/v1/ai/results/{r.id}/image" if r.image_path else None,
        "source_url": r.source_url,
        "review_state": r.review_state,
        "has_image": bool(r.image_path),
        "boxes": json.loads(r.boxes_json) if r.boxes_json else [],
        "ts": r.ts.isoformat(timespec="seconds") if r.ts else None,
        "alarm_id": r.alarm_id,
        "alarm_level": alarm_level,
        # 演示种子行（source_id=99）：前端据此打 DEMO 角标，别和真实回调混在一起
        "demo": r.source_id == DEMO_SOURCE_ID,
    }


@router.get("/algorithms")
def list_algorithms(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[dict]:
    # 首次访问时把常用算法种进去（不依赖迁移里的数据）
    if db.query(AiAlgorithm).count() == 0:
        for code, name, cat, unit in DEFAULT_ALGORITHMS:
            db.add(AiAlgorithm(code=code, name=name, category=cat, unit=unit))
        db.commit()
    return [
        {"code": a.code, "name": a.name, "category": a.category, "unit": a.unit,
         "min_confidence": a.min_confidence, "enabled": a.enabled}
        for a in db.query(AiAlgorithm).order_by(AiAlgorithm.id).all()
    ]


def _auth_kind(client: dict) -> str:
    return client["kind"]


@router.post("/results")
def push_result(
    body: ResultIn,
    db: Session = Depends(get_db),
    client: dict = Depends(require_scope("ai:write")),
) -> dict:
    kind = _auth_kind(client)

    algo = db.query(AiAlgorithm).filter(AiAlgorithm.code == body.algorithm).first()
    if algo is None:
        raise BadRequest(f"未注册的算法 {body.algorithm}", code="UNKNOWN_ALGORITHM")
    if not algo.enabled:
        raise BadRequest(f"算法 {algo.code} 已停用", code="ALGORITHM_DISABLED")

    # 秒级截断：幂等键要稳定，否则同一帧重推会被当成两条
    ts = (body.ts or datetime.now()).replace(microsecond=0)
    dup = (
        db.query(AiResult)
        .filter(AiResult.algorithm == body.algorithm,
                AiResult.camera_id == body.camera_id,
                AiResult.ts == ts)
        .first()
    )
    if dup:
        return {**_out(dup, algo.name), "duplicated": True}

    image_path = _save_image(body.image_base64) if body.image_base64 else None
    rec = AiResult(
        algorithm=body.algorithm, camera_id=body.camera_id, point_id=body.point_id,
        value=body.value, text=body.text, confidence=body.confidence,
        image_path=image_path, ts=ts,
        boxes_json=json.dumps(body.boxes, ensure_ascii=False) if body.boxes else None,
    )
    db.add(rec)
    db.commit()          # 先把结果写进去：告警走另一个 session，不能和这里抢写锁
    db.refresh(rec)

    # 置信度够高才报警；阈值可在算法表里按算法调
    if body.confidence >= algo.min_confidence:
        from app.services import alarms as alarms_mod

        store = alarms_mod.get_store()
        if store is not None:
            alarm = store.raise_external(
                metric=f"ai_{body.algorithm}", level="warn",
                message=body.text or f"{algo.name} 触发（置信度 {body.confidence:.2f}）",
                value=body.value, camera_id=body.camera_id,
            )
            if alarm is not None and alarm.id:
                rec.alarm_id = alarm.id
                db.commit()
                db.refresh(rec)
    return {**_out(rec, algo.name), "duplicated": False, "auth": kind}


# 页面上的告警级别口径：P1/critical、P2/warn；none 表示没建告警的结果。
# 其他值一律忽略（不加过滤），避免脏参数把列表筛空。
LEVEL_FILTER = {"p1": "critical", "p2": "warn"}


@router.get("/results")
def list_results(
    algorithm: str | None = None,
    camera_id: int | None = None,
    external_camera_id: int | None = None,
    min_confidence: float | None = None,
    level: str | None = None,
    since: datetime | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """结果列表：默认按 id 倒序（最新在前），limit 硬上限 200。"""
    q = db.query(AiResult).order_by(AiResult.id.desc())
    if algorithm:
        q = q.filter(AiResult.algorithm == algorithm)
    if camera_id is not None:
        q = q.filter(AiResult.camera_id == camera_id)
    if external_camera_id is not None:
        q = q.filter(AiResult.external_camera_id == external_camera_id)
    if min_confidence is not None:
        q = q.filter(AiResult.confidence >= min_confidence)
    if level in LEVEL_FILTER:
        # EXISTS 而不是 join：alarm_record 一条对一条，但 EXISTS 不会因关联把结果行翻倍
        q = q.filter(
            db.query(AlarmRecord.id)
            .filter(
                AlarmRecord.id == AiResult.alarm_id,
                AlarmRecord.level == LEVEL_FILTER[level],
            )
            .exists()
        )
    elif level == "none":
        q = q.filter(AiResult.alarm_id.is_(None))
    if since is not None:
        # 库里 ts 是无时区的本地时间；带 Z/偏移的入参先换算成本地 naive 再比
        if since.tzinfo is not None:
            since = since.astimezone().replace(tzinfo=None)
        q = q.filter(AiResult.ts >= since)
    rows = q.limit(max(1, min(limit, 200))).all()
    names = {a.code: a.name for a in db.query(AiAlgorithm).all()}
    # 一次查完这页的告警级别，避免每行再查一次
    alarm_ids = [r.alarm_id for r in rows if r.alarm_id]
    levels = dict(
        db.query(AlarmRecord.id, AlarmRecord.level)
        .filter(AlarmRecord.id.in_(alarm_ids))
        .all()
    ) if alarm_ids else {}
    return {
        "total": len(rows),
        "items": [
            _out(r, names.get(r.algorithm), levels.get(r.alarm_id))
            for r in rows
        ],
    }


@router.get("/results/stats")
def result_stats(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """结果总览：给页面顶部统计卡和相机/算法分组用。

    P1/P2 只统计真的建了告警的结果（alarm_id 能 join 到 alarm_record），
    告警级别沿用平台既有口径：critical=P1、warn=P2。
    """
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    total = db.query(func.count(AiResult.id)).scalar() or 0
    today = (
        db.query(func.count(AiResult.id))
        .filter(AiResult.ts >= today_start)
        .scalar() or 0
    )

    camera_rows = (
        db.query(
            AiResult.external_camera_id,
            func.max(AiResult.external_camera_name),
            func.count(AiResult.id),
        )
        .group_by(AiResult.external_camera_id)
        .order_by(func.count(AiResult.id).desc())
        .all()
    )
    algorithm_rows = (
        db.query(AiResult.algorithm, func.count(AiResult.id))
        .group_by(AiResult.algorithm)
        .order_by(func.count(AiResult.id).desc())
        .limit(10)
        .all()
    )

    p1 = (
        db.query(func.count(AiResult.id))
        .join(AlarmRecord, AlarmRecord.id == AiResult.alarm_id)
        .filter(AlarmRecord.level == "critical")
        .scalar() or 0
    )
    p2 = (
        db.query(func.count(AiResult.id))
        .join(AlarmRecord, AlarmRecord.id == AiResult.alarm_id)
        .filter(AlarmRecord.level == "warn")
        .scalar() or 0
    )
    demo = (
        db.query(func.count(AiResult.id))
        .filter(AiResult.source_id == DEMO_SOURCE_ID)
        .scalar() or 0
    )
    return {
        "total": total,
        "today": today,
        "p1": p1,
        "p2": p2,
        "demo": demo,
        "by_camera": [
            {"external_camera_id": cid, "camera_name": name, "count": count}
            for cid, name, count in camera_rows
        ],
        "by_algorithm": [
            {"algorithm": algo, "count": count}
            for algo, count in algorithm_rows
        ],
    }


@router.get("/streams")
def list_streams(
    robot_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    q = db.query(AiStream).order_by(AiStream.id)
    if robot_id is not None:
        q = q.filter(AiStream.robot_id == robot_id)
    items = [
        {"id": s.id, "robot_id": s.robot_id, "stream_type": s.stream_type,
         "role": s.role, "channel": s.channel, "resolution": s.resolution,
         "fps": s.fps, "codec": s.codec, "status": s.status, "note": s.note}
        for s in q.all()
    ]
    return {"total": len(items), "items": items}


class SnapshotIn(BaseModel):
    stream_id: int
    preset_id: int | None = None


def _do_capture(db: Session, s: AiStream, preset_id: int | None) -> dict:
    """抓一路并写一条 snapshot 结果；失败抛 BadRequest。"""
    from urllib.parse import urlsplit

    from app.services.snapshot import capture_isapi, save_ai_shot

    if s.status != "active" or not s.rtsp_url:
        raise BadRequest("视频流未启用或没有地址", code="STREAM_INACTIVE")
    u = urlsplit(s.rtsp_url)
    if not u.hostname or not u.username:
        raise BadRequest("视频流地址缺少主机或账号", code="BAD_STREAM_URL")
    channel = s.channel or "101"
    picture = f"http://{u.hostname}/ISAPI/Streaming/channels/{channel}/picture"
    try:
        data = capture_isapi(picture, u.username, u.password or "")
        saved = save_ai_shot(data, s.stream_type)
    except RuntimeError as exc:
        raise BadRequest(str(exc), code="SNAPSHOT_FAILED") from exc

    rec = AiResult(
        algorithm="snapshot",
        preset_id=preset_id,
        stream_type=s.stream_type,
        image_path=saved["path"],
        confidence=1.0,
        ts=datetime.now().replace(microsecond=0),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return {"result_id": rec.id, "stream_id": s.id, "stream_type": s.stream_type,
            "preset_id": preset_id, **saved,
            "captured_at": rec.ts.isoformat(timespec="seconds")}


@router.post("/snapshots/capture")
def capture_snapshot(
    body: SnapshotIn,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
) -> dict:
    """按 ai_stream 用 ISAPI Digest 抓一张 JPEG，落盘并返回地址。"""
    s = db.get(AiStream, body.stream_id)
    if s is None:
        raise NotFound("视频流不存在")
    return _do_capture(db, s, body.preset_id)


class PtzCaptureIn(BaseModel):
    preset_id: int
    dwell_s: int = 20
    stream_ids: list[int] = Field(default_factory=list)


@router.post("/ptz/goto_capture")
def ptz_goto_capture(
    body: PtzCaptureIn,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
) -> dict:
    """转到预置位，等 dwell 秒，再抓指定流。

    P0 用固定 dwell；位置校验（ISAPI status 容差）留在下一版。
    """
    import time

    from app.services import ptz_presets

    if not 1 <= body.preset_id <= 32:
        raise BadRequest("预置位必须是 1–32", code="BAD_PRESET")
    ok, why = ptz_presets.goto_preset(body.preset_id)
    if not ok:
        raise BadRequest(f"转到预置位失败：{why}", code="PTZ_GOTO_FAILED")
    dwell = max(0, min(int(body.dwell_s), 60))
    if dwell:
        time.sleep(dwell)

    ids = body.stream_ids or [
        s.id for s in db.query(AiStream)
        .filter(AiStream.robot_id == 2, AiStream.status == "active")
        .filter(AiStream.stream_type.in_(["visible", "thermal"]))
        .all()
    ]
    out = []
    for sid in ids:
        s = db.get(AiStream, sid)
        if s is None:
            continue
        out.append(_do_capture(db, s, body.preset_id))
    return {"preset_id": body.preset_id, "dwell_s": dwell, "captures": out}


@router.get("/snapshots/{day}/{name}")
def get_snapshot(day: str, name: str):
    """抓图文件访问。day=YYYYMMDD，name 只取 basename，防目录穿越。"""
    from app.services.snapshot import AI_SHOT_ROOT

    safe_name = Path(name).name
    path = AI_SHOT_ROOT / day / safe_name
    if not path.exists():
        raise NotFound("图片不存在")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/results/{result_id}/image")
def get_result_image(
    result_id: int, db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    r = db.get(AiResult, result_id)
    if not r or not r.image_path:
        raise NotFound("没有原图")
    path = Path(__file__).resolve().parents[3] / "data" / r.image_path
    if not path.exists():
        raise NotFound("原图文件丢失")
    return FileResponse(path, media_type="image/jpeg")
