"""工单自动化：告警自动建单 + 超时自动升级。

PPT 的模块五要的是"异常自动进工单"和"超时未处置自动升级"，
这两件事不能靠人点按钮，必须有后台触发点。
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

from app.models.inspection import WorkOrder

log = logging.getLogger(__name__)


def ensure_from_alarm(db, alarm) -> WorkOrder | None:
    """严重告警自动建工单（同一告警只建一次，已销号的不再建）。

    返回新建的工单；已存在则返回 None。
    """
    alarm_id = getattr(alarm, "id", None)
    if not alarm_id:
        return None
    exists = (
        db.query(WorkOrder)
        .filter(WorkOrder.source == "alarm", WorkOrder.source_id == alarm_id)
        .first()
    )
    if exists:
        return None

    seq = (db.query(WorkOrder).count() or 0) + 1
    order = WorkOrder(
        code=f"WO-{datetime.now().strftime('%Y%m%d')}-{seq:03d}",
        title=(getattr(alarm, "message", None) or "告警")[:120],
        source="alarm",
        source_id=alarm_id,
        level=getattr(alarm, "level", "warn") or "warn",
        status="open",
        description=(getattr(alarm, "message", None) or "")[:500],
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    log.info("告警 %s 自动建工单 %s", alarm_id, order.code)
    return order


def escalate_overdue(session_factory) -> int:
    """超期未销号的工单标记升级（只升一次）。返回升级条数。"""
    from app.services.messages import store as msg_store

    now = datetime.now()
    n = 0
    with session_factory() as db:
        rows = (
            db.query(WorkOrder)
            .filter(
                WorkOrder.status != "closed",
                WorkOrder.due_at.isnot(None),
                WorkOrder.due_at < now,
                WorkOrder.escalated_at.is_(None),
            )
            .all()
        )
        for o in rows:
            o.escalated_at = now
            n += 1
        db.commit()
        for o in rows:
            msg_store.add(
                "warn", "work_order", f"工单超期升级：{o.title}",
                f"{o.code or '#' + str(o.id)} 超过期限未处置，已上报值班长",
                {"to": "work-orders"},
            )
    return n


class WorkOrderEscalator:
    def __init__(self, session_factory, interval_s: int = 300) -> None:
        self._sf = session_factory
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        if self._stop.wait(45):
            return
        while not self._stop.is_set():
            try:
                n = escalate_overdue(self._sf)
                if n:
                    log.warning("超期工单升级 %s 条", n)
            except Exception:  # noqa: BLE001
                log.exception("工单升级检查失败")
            if self._stop.wait(self.interval_s):
                break


escalator: WorkOrderEscalator | None = None
