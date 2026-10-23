"""消息中心接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import require_roles
from app.models.user import User
from app.services.messages import store

router = APIRouter(prefix="/messages", tags=["messages"])


@router.get("")
def list_messages(
    limit: int = Query(default=100, le=200),
    since: float = Query(default=0.0, description="只要这个时间戳之后的消息数"),
    _: User = Depends(require_roles("admin", "operator", "viewer")),
) -> dict:
    # 服务端记录的已读时间戳优先（换浏览器/刷新也保持已读）
    from app.db.session import SessionLocal
    from app.models.setting import Setting

    try:
        with SessionLocal() as db:
            row = db.get(Setting, "message.read_ts")
            if row is not None and row.value_json:
                since = max(since, float(row.value_json))
    except Exception:  # noqa: BLE001
        pass

    items = store.list(limit)
    return {
        "items": [
            {
                "id": m.id, "ts": m.ts, "level": m.level, "source": m.source,
                "title": m.title, "body": m.body, "link": m.link,
            }
            for m in items
        ],
        "unread": store.unread(since),
    }


@router.post("/read-all", dependencies=[Depends(__import__("app.api.deps", fromlist=["require_csrf"]).require_csrf)])
def mark_all_read(me: User = Depends(require_roles("admin", "operator", "viewer"))) -> dict:
    """全部标为已读（服务端记录时间戳，刷新/换设备也保持已读）。"""
    from datetime import datetime

    from app.models.setting import Setting

    from app.db.session import SessionLocal

    ts = datetime.now().timestamp()
    with SessionLocal() as db:
        row = db.get(Setting, "message.read_ts")
        if row is None:
            row = Setting(key="message.read_ts", value_json=str(ts))
            db.add(row)
        else:
            row.value_json = str(ts)
        db.commit()
    return {"ok": True, "read_ts": ts}
