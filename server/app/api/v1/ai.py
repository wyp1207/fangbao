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
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.services.api_auth import require_scope, session_or_key
from app.core.errors import BadRequest, NotFound, PlatformError
from app.db.session import get_db
from app.models.ai import AiAlgorithm, AiResult
from app.models.user import User

router = APIRouter(prefix="/ai", tags=["ai"])

ROOT = Path(__file__).resolve().parents[3] / "data" / "ai_images"

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


def _out(r: AiResult, algorithm_name: str | None = None) -> dict:
    return {
        "id": r.id, "algorithm": r.algorithm, "algorithm_name": algorithm_name or r.algorithm,
        "camera_id": r.camera_id, "point_id": r.point_id,
        "value": r.value, "text": r.text, "confidence": r.confidence,
        "image": f"/api/v1/ai/results/{r.id}/image" if r.image_path else None,
        "has_image": bool(r.image_path),
        "boxes": json.loads(r.boxes_json) if r.boxes_json else [],
        "ts": r.ts.isoformat(timespec="seconds") if r.ts else None,
        "alarm_id": r.alarm_id,
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


@router.get("/results")
def list_results(
    algorithm: str | None = None,
    camera_id: int | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    q = db.query(AiResult).order_by(AiResult.id.desc())
    if algorithm:
        q = q.filter(AiResult.algorithm == algorithm)
    if camera_id is not None:
        q = q.filter(AiResult.camera_id == camera_id)
    rows = q.limit(min(limit, 200)).all()
    names = {a.code: a.name for a in db.query(AiAlgorithm).all()}
    return {"total": len(rows), "items": [_out(r, names.get(r.algorithm)) for r in rows]}


@router.get("/results/{result_id}/image")
def get_result_image(
    result_id: int, db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from fastapi.responses import FileResponse

    r = db.get(AiResult, result_id)
    if not r or not r.image_path:
        raise NotFound("没有原图")
    path = Path(__file__).resolve().parents[3] / "data" / r.image_path
    if not path.exists():
        raise NotFound("原图文件丢失")
    return FileResponse(path, media_type="image/jpeg")
