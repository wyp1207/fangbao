"""平台设置：读写 + 生效。

读取顺序：数据库 > .env 默认值。
每次读都走一个小缓存（2 秒），避免轮询循环每一轮都查库。
"""

from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_csrf, require_roles
from app.core.config import get_settings
from app.core.errors import BadRequest
from app.db.session import get_db
from app.models.setting import Setting, set_value
from app.models.user import User
from app.services import settings_schema as schema
from app.services.messages import audit, store as msg_store

router = APIRouter(prefix="/settings", tags=["settings"])

_cache: dict[str, Any] = {}
_cache_at: float = 0.0
_lock = threading.Lock()
_TTL = 2.0


def _env_default(key: str) -> Any:
    """数据库没有时，回落到 .env 里的值（老部署不配也不出错）。"""
    s = get_settings()
    mapping = {
        "record.keep_days": "record_keep_days",
        "record.max_gb": "record_max_gb",
        "record.min_free_gb": "record_min_free_gb",
        "record.enabled": "recording_enabled",
        "video.transcode_width": "video_scale_width",
    }
    attr = mapping.get(key)
    if attr and hasattr(s, attr):
        return getattr(s, attr)
    return schema.SCHEMA[key]["default"]


def load_all(db: Session | None = None) -> dict[str, Any]:
    """一次取全量设置（带 2 秒缓存）。"""
    global _cache, _cache_at
    now = time.monotonic()
    with _lock:
        if _cache and now - _cache_at < _TTL:
            return dict(_cache)

    values = {k: _env_default(k) for k in schema.SCHEMA}
    close = False
    if db is None:
        from app.db.session import SessionLocal
        db = SessionLocal()
        close = True
    try:
        for row in db.query(Setting).all():
            if row.key in values:
                try:
                    values[row.key] = row.value(values[row.key])
                except Exception:  # noqa: BLE001
                    pass
    finally:
        if close:
            db.close()

    with _lock:
        _cache = dict(values)
        _cache_at = now
    return values


def get(key: str, default: Any = None) -> Any:
    return load_all().get(key, default)


def invalidate() -> None:
    global _cache_at
    with _lock:
        _cache_at = 0.0


# ---------------- API ----------------

class SettingPatch(BaseModel):
    values: dict[str, Any]


@router.get("")
def read_settings(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    values = load_all(db)
    rows = {r.key: {"updated_at": r.updated_at.isoformat(timespec="seconds") if r.updated_at else None,
                    "updated_by": r.updated_by, "version": r.version}
            for r in db.query(Setting).all()}
    return {"values": values, "schema": schema.describe(), "meta": rows}


@router.put("", dependencies=[Depends(require_csrf)])
def update_settings(
    body: SettingPatch,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin")),
) -> dict:
    if not body.values:
        raise BadRequest("没有要保存的项", code="EMPTY")

    changed: dict[str, Any] = {}
    for key, raw in body.values.items():
        if key not in schema.SCHEMA:
            raise BadRequest(f"未知设置项 {key}", code="UNKNOWN_KEY")
        try:
            value = schema.cast(key, raw)
        except ValueError as exc:
            raise BadRequest(str(exc), code="BAD_VALUE") from exc
        set_value(db, key, value, who=me.username)
        changed[key] = value

    invalidate()
    audit(db=db, action="settings.update", target=",".join(changed), user=me, detail=changed)
    msg_store.add("warn", "system", f"配置已修改：{', '.join(schema.SCHEMA[k]['label'] for k in changed)}",
                  f"操作人 {me.username}", {"to": "settings"})
    _apply_side_effects(changed, db)
    return {"ok": True, "values": load_all(db), "changed": changed}


def _apply_side_effects(changed: dict[str, Any], db: Session) -> None:
    """立即生效的部分：录像开关、告警阈值由各自模块下次读取时生效。"""
    from app.services.recorder import registry

    if changed.get("record.enabled") is False:
        registry.stop_all()
