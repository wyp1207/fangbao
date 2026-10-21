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
