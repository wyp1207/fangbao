"""任务执行事件时间线（服务层）。

`task_run.status` 只是一个"当前值"：下发没到、点位重试、取消没停住，这些过程
在状态字段里全都看不见。这张表把每次状态迁移按 (run_id, seq) 追加下来，
前端详情弹层按 seq 渲染成一条时间线。

参考但不依赖：Open-RMF 的 task state 迁移、Nav2 行为树节点事件、
Temporal 的 activity history。相同点只有"一步一条、只追加、带时间"，
没有任何外部运行时依赖。

约定：
- 只追加（append-only）：改事件等于改历史，不提供 update/delete；
- seq 按 run 递增、从 1 开始；用 max(seq)+1 算，跨进程也不会退号；
- 落事件失败**不能**影响主流程：业务代码统一调用 `safe_log`，
  它内部 try/except，只记日志、不抛、不回滚业务事务。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.task_run import TaskEvent

logger = logging.getLogger(__name__)

# 稳定字面量 → 中文标签。前端也有一份（离线时也能显示），两边都只追加不改。
KIND_LABELS = {
    "created": "创建",
    "dispatched": "已下发",
    "paused": "暂停",
    "resumed": "继续",
    "cancelled": "取消",
    "step_retry": "步骤重试",
    "done": "完成",
    "failed": "失败",
}


def _next_seq(db: Session, run_id: int) -> int:
    cur = db.scalar(
        select(func.max(TaskEvent.seq)).where(TaskEvent.run_id == run_id)
    )
    return int(cur or 0) + 1


def log(db: Session, run_id: int, kind: str, message: str,
        data: dict | None = None, actor: str = "system") -> TaskEvent:
    """追加一条事件（不 commit，跟随调用方的事务）。seq 按 run 递增。"""
    event = TaskEvent(
        run_id=run_id,
        seq=_next_seq(db, run_id),
        kind=(kind or "")[:24],
        message=(message or "")[:255],
        data_json=json.dumps(data, ensure_ascii=False) if data is not None else None,
        actor=(actor or "system")[:64],
        created_at=datetime.now(),
    )
    # 用 SAVEPOINT 包一层：就算写库本身失败，也不会把业务事务打成
    # "PendingRollbackError"（那样主流程的 commit 反而会挂）。
    try:
        with db.begin_nested():
            db.add(event)
            db.flush()
    except Exception:
        if db.contains(event):
            db.expunge(event)
        raise
    return event


def safe_log(db: Session, run_id: int, kind: str, message: str,
             data: dict | None = None, actor: str = "system") -> TaskEvent | None:
    """主流程入口：事件落不下去只记日志，绝不打断下发/暂停/取消。"""
    try:
        return log(db, run_id, kind, message, data=data, actor=actor)
    except Exception:  # noqa: BLE001
        logger.warning("任务事件写入失败 run=%s kind=%s（主流程继续）",
                       run_id, kind, exc_info=True)
        return None


def list_events(db: Session, run_id: int) -> list[TaskEvent]:
    """按 seq 升序返回一条 run 的全部事件。"""
    return (
        db.query(TaskEvent)
        .filter(TaskEvent.run_id == run_id)
        .order_by(TaskEvent.seq.asc(), TaskEvent.id.asc())
        .all()
    )
