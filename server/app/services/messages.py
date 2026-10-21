"""消息中心 + 审计：两套持久化。

- `MessageStore`：给"消息中心"页面看的事件流（视频注册、账号变更、抓帧失败…）。
- `audit()`：给安环/等保看的操作审计（谁在什么时候做了什么），写 operation_log 表。

两者区别：消息是"给人看的通知"，审计是"给检查看的凭证"，不要混在一张表。
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

Level = Literal["info", "warn", "danger"]


@dataclass
class Message:
    id: int
    ts: float
    level: Level
    source: str
    title: str
    body: str = ""
    link: dict[str, Any] = field(default_factory=dict)


class MessageStore:
    def __init__(self, capacity: int = 500) -> None:
        self._items: list[Message] = []
        self._capacity = capacity
        self._lock = threading.Lock()
        self._session_factory: Callable[[], Session] | None = None

    def attach_db(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def add(self, level: Level, source: str, title: str, body: str = "",
            link: dict[str, Any] | None = None) -> Message:
        link = link or {}
        msg = Message(0, time.time(), level, source, title, body, link)
        if self._session_factory is not None:
            from app.models.message import MessageRecord

            try:
                with self._session_factory() as db:  # type: ignore[misc]
                    rec = MessageRecord(
                        ts=datetime.now(), level=level, source=source,
                        title=title[:250], body=body or None,
                        link_json=json.dumps(link, ensure_ascii=False) if link else None,
                    )
                    db.add(rec)
                    db.commit()
                    db.refresh(rec)
                    msg.id = rec.id
                    msg.ts = rec.ts.timestamp() if rec.ts else time.time()
            except Exception:  # noqa: BLE001 - 消息写失败不能影响主流程
                pass
        with self._lock:
            self._items.append(msg)
            if len(self._items) > self._capacity:
                self._items = self._items[-self._capacity:]
        return msg

    def list(self, limit: int = 100) -> list[Message]:
        if self._session_factory is not None:
            from app.models.message import MessageRecord

            with self._session_factory() as db:  # type: ignore[misc]
                rows = db.scalars(
                    select(MessageRecord).order_by(MessageRecord.ts.desc()).limit(limit)
                ).all()
                out = []
                for r in rows:
                    try:
                        link = json.loads(r.link_json) if r.link_json else {}
                    except Exception:  # noqa: BLE001
                        link = {}
                    out.append(Message(
                        r.id, r.ts.timestamp() if r.ts else 0, r.level, r.source,
                        r.title, r.body or "", link,
                    ))
                return out
        with self._lock:
            return list(reversed(self._items[-limit:]))

    def unread(self, since_ts: float) -> int:
        return sum(1 for m in self.list(500) if m.ts > since_ts)


store = MessageStore()


def audit(db: Session, *, action: str, target: str | None = None,
          user: Any = None, detail: dict | None = None,
          client_ip: str | None = None, success: bool = True,
          summary: str | None = None) -> None:
    """写一条操作审计。调用方传 db 会话，事务跟着调用方走。"""
    from app.models.operation_log import OperationLog

    try:
        row = OperationLog(
            ts=datetime.now(),
            user_id=getattr(user, "id", None),
            username=getattr(user, "username", None),
            client_ip=client_ip,
            action=action,
            target=target,
            params_json=json.dumps(detail, ensure_ascii=False, default=str) if detail else None,
            success=success,
            result_summary=summary,
        )
        db.add(row)
        db.commit()
    except Exception:  # noqa: BLE001 - 审计失败不影响业务，但要留在日志里
        import logging
        logging.getLogger(__name__).exception("写审计失败 action=%s", action)


def audit_list(db: Session, *, limit: int = 100, offset: int = 0,
               action: str | None = None, username: str | None = None) -> dict:
    from sqlalchemy import and_, func, select

    from app.models.operation_log import OperationLog

    conds = []
    if action:
        conds.append(OperationLog.action == action)
    if username:
        conds.append(OperationLog.username == username)
    where = and_(*conds) if conds else None

    q = select(OperationLog).order_by(OperationLog.id.desc()).limit(limit).offset(offset)
    if where is not None:
        q = q.where(where)
    total_q = select(func.count()).select_from(OperationLog)
    if where is not None:
        total_q = total_q.where(where)

    rows = db.scalars(q).all()
    return {
        "total": db.scalar(total_q) or 0,
        "items": [
            {
                "id": r.id,
                "ts": r.ts.isoformat(timespec="seconds") if r.ts else None,
                "username": r.username,
                "client_ip": r.client_ip,
                "action": r.action,
                "target": r.target,
                "success": r.success,
                "summary": r.result_summary,
                "detail": r.params_json,
            }
            for r in rows
        ],
    }
