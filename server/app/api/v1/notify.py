"""告警通知通道：CRUD + 测试发送 + 投递记录。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_csrf, require_roles
from app.core.errors import BadRequest, NotFound
from app.db.session import get_db
from app.models.notify import NotifyChannel, NotifyLog
from app.models.user import User
from app.services import notify as notify_svc
from app.services.messages import audit

router = APIRouter(prefix="/notify", tags=["notify"])

SECRET_KEYS = ("url", "password")


def _mask(config: dict) -> dict:
    """URL 里通常带 key，邮件带密码——返回时统一打码。"""
    out = dict(config)
    for k in SECRET_KEYS:
        v = out.get(k)
        if isinstance(v, str) and v:
            out[k] = v[:8] + "***" + v[-4:] if len(v) > 14 else "***"
    return out


def _out(ch: NotifyChannel) -> dict:
    try:
        cfg = json.loads(ch.config_json or "{}")
    except Exception:  # noqa: BLE001
        cfg = {}
    return {
        "id": ch.id, "name": ch.name, "type": ch.type,
        "type_label": notify_svc.TYPE_LABELS.get(ch.type, ch.type),
        "config": _mask(cfg),
        "min_level": ch.min_level, "min_interval_min": ch.min_interval_min,
        "tier": ch.tier,
        "enabled": ch.enabled, "note": ch.note,
        "created_at": ch.created_at.isoformat(timespec="seconds") if ch.created_at else None,
    }


class ChannelIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    type: str
    config: dict = Field(default_factory=dict)
    min_level: str = "critical"
    tier: int = 1
    min_interval_min: int = 10
    enabled: bool = True
    note: str | None = None


@router.get("/meta")
def meta(_: User = Depends(get_current_user)) -> dict:
    return {
        "types": [{"value": k, "label": v} for k, v in notify_svc.TYPE_LABELS.items()],
        "levels": [{"value": "warn", "label": "提醒及以上"}, {"value": "critical", "label": "仅严重"}],
    }


@router.get("/channels")
def list_channels(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[dict]:
    return [_out(c) for c in db.query(NotifyChannel).order_by(NotifyChannel.id).all()]


@router.post("/channels", dependencies=[Depends(require_csrf)])
def create_channel(
    body: ChannelIn,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin")),
) -> dict:
    if body.type not in notify_svc.TYPE_LABELS:
        raise BadRequest(f"未知通道类型 {body.type}", code="BAD_TYPE")
    if body.min_level not in ("warn", "critical"):
        raise BadRequest("min_level 只能是 warn 或 critical", code="BAD_LEVEL")
    if body.type in ("wecom", "dingtalk", "generic") and not body.config.get("url"):
        raise BadRequest("该类型必须填 URL", code="NO_URL")
    if body.type == "email" and not (body.config.get("host") and body.config.get("to")):
        raise BadRequest("邮件通道必须填 SMTP 主机和收件人", code="NO_SMTP")

    ch = NotifyChannel(
        name=body.name, type=body.type,
        config_json=json.dumps(body.config, ensure_ascii=False),
        min_level=body.min_level, tier=2 if body.tier == 2 else 1,
        min_interval_min=max(0, body.min_interval_min),
        enabled=body.enabled, note=body.note,
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)
    audit(db=db, action="notify.create", target=ch.name, user=me,
          detail={"type": ch.type, "min_level": ch.min_level})
    return _out(ch)


@router.patch("/channels/{channel_id}", dependencies=[Depends(require_csrf)])
def update_channel(
    channel_id: int, body: dict,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin")),
) -> dict:
    ch = db.get(NotifyChannel, channel_id)
    if not ch:
        raise NotFound("通道不存在")

    if "config" in body and isinstance(body["config"], dict):
        # 打码串原样提交回来时，保留原值
        old = json.loads(ch.config_json or "{}")
        new = dict(body["config"])
        for k in SECRET_KEYS:
            v = new.get(k)
            if isinstance(v, str) and "***" in v:
                new[k] = old.get(k, "")
        ch.config_json = json.dumps(new, ensure_ascii=False)
    for k in ("name", "min_level", "min_interval_min", "enabled", "note", "tier"):
        if k in body and body[k] is not None:
            setattr(ch, k, body[k])
    db.commit()
    db.refresh(ch)
    audit(db=db, action="notify.update", target=ch.name, user=me)
    return _out(ch)


@router.delete("/channels/{channel_id}", dependencies=[Depends(require_csrf)])
def delete_channel(
    channel_id: int, db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin")),
) -> dict:
    ch = db.get(NotifyChannel, channel_id)
    if not ch:
        raise NotFound("通道不存在")
    db.delete(ch)
    db.commit()
    audit(db=db, action="notify.delete", target=ch.name, user=me)
    return {"ok": True}


@router.post("/channels/{channel_id}/test", dependencies=[Depends(require_csrf)])
def test_channel(
    channel_id: int, db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin")),
) -> dict:
    """发一条测试消息，走真实发送逻辑，结果如实返回。"""
    ch = db.get(NotifyChannel, channel_id)
    if not ch:
        raise NotFound("通道不存在")

    sample = {
        "id": 0, "metric": "test", "level": "critical",
        "message": "这是一条测试告警（来自平台「告警通知」页）",
        "started_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
    }
    ok, status = notify_svc.send_once(ch, sample)
    db.add(NotifyLog(ts=__import__("datetime").datetime.now(), channel_id=ch.id,
                     channel_name=ch.name, alarm_id=None, payload=notify_svc._text(sample),
                     ok=ok, status=status[:60], error=None if ok else status[:500]))
    db.commit()
    audit(db=db, action="notify.test", target=ch.name, user=me,
          success=ok, summary=status[:120])
    return {"ok": ok, "status": status}


@router.get("/logs")
def list_logs(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    only_failed: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    from sqlalchemy import func, select

    q = select(NotifyLog).order_by(NotifyLog.id.desc())
    if only_failed:
        q = q.where(NotifyLog.ok.is_(False))
    rows = db.scalars(q.limit(limit).offset(offset)).all()
    total_q = select(func.count()).select_from(NotifyLog)
    if only_failed:
        total_q = total_q.where(NotifyLog.ok.is_(False))
    return {
        "total": db.scalar(total_q) or 0,
        "items": [
            {"id": r.id, "ts": r.ts.isoformat(timespec="seconds") if r.ts else None,
             "channel_name": r.channel_name, "alarm_id": r.alarm_id,
             "ok": r.ok, "status": r.status, "error": r.error}
            for r in rows
        ],
    }
