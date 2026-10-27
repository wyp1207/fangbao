"""任务互斥 + 人工接管。

为什么需要：
- 两个人同时点"下发巡航"，同一台车会收到两条订单，谁先谁后无法保证，车会来回横跳；
- 巡航中有人要手动把车开回去，必须能抢占，否则控制指令和自动任务互相打架。

做法（最小可用）：
- 同一台车同一时刻只允许一个 running 的 TaskRun；
- 下发/巡航前检查，占用则 409 RUN_BUSY 并告知占用的是哪条；
- 人工接管：把该车所有 running 任务置为 cancelled（原因写"人工接管"），再允许手动控制。
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


def active_run(db: Session, robot_id: int) -> dict | None:
    """返回该车当前正在跑的任务（没有就 None）。"""
    from app.models.task_run import TaskRun

    row = (
        db.query(TaskRun)
        .filter(TaskRun.status == "running", TaskRun.robot_id == robot_id)
        .order_by(TaskRun.id.desc())
        .first()
    )
    if row is None:
        return None
    return {"id": row.id, "name": row.name, "status": row.status}


def assert_free(db: Session, robot_id: int, run_id: int) -> None:
    """下发前检查：这台车没有别的任务在跑。"""
    from app.core.errors import PlatformError

    busy = active_run(db, robot_id)
    if busy and busy["id"] != run_id:
        raise PlatformError(
            f"这台车还在执行任务 #{busy['id']}「{busy['name']}」，先停止或接管再下发",
            code="RUN_BUSY",
            status_code=409,
        )


def takeover(db: Session, robot_id: int, *, reason: str = "人工接管") -> int:
    """人工接管：取消这台车所有运行中的任务，返回取消条数。"""
    from app.models.task_run import TaskRun

    rows = (
        db.query(TaskRun)
        .filter(TaskRun.status == "running", TaskRun.robot_id == robot_id)
        .all()
    )
    for row in rows:
        row.status = "cancelled"
        row.finished_at = datetime.now()
        row.dispatch_error = reason
    if rows:
        db.commit()
        log.warning("人工接管：设备 %s 取消任务 %s", robot_id, [r.id for r in rows])
    return len(rows)
