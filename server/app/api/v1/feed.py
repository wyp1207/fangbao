"""首页「实时消息」数据源：巡检 / 告警 / 控制 三类消息统一出口。

为什么要一个聚合接口：首页原来只显示告警，切 tab 没有数据可切；
三类消息来自不同表（巡检任务步骤、告警、审计日志），
在前端拼会重复写三套取数逻辑，放在后端一处归一化。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.alarm import AlarmRecord
from app.models.operation_log import OperationLog
from app.models.task_run import TaskRun, TaskRunStep
from app.models.user import User

router = APIRouter(tags=["feed"])


def _fmt(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


@router.get("/dashboard/feed")
def feed(
    kind: str = Query("alarm", pattern="^(patrol|alarm|control)$"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """返回 {kind, items:[{id, ts, text, level, link}]}，link 直接给前端跳转用。"""
    items: list[dict] = []

    if kind == "alarm":
        rows = (db.query(AlarmRecord).order_by(AlarmRecord.started_at.desc())
                .limit(limit).all())
        for a in rows:
            acked = a.acked_at is not None
            items.append({
                "id": a.id,
                "ts": _fmt(a.started_at),
                "text": a.message,
                "level": "critical" if a.level == "critical" else "warn",
                "badge": "已确认" if acked else "未确认",
                "link": f"/alarms?focus={a.id}",
            })

    elif kind == "patrol":
        # 有人工巡检/巡航跑过就该有记录：不只看 finished_at，失败/跳过的也要能出现在消息里
        rows = (db.query(TaskRunStep)
                .filter(TaskRunStep.status.in_(("ok", "failed", "skipped")))
                .order_by(TaskRunStep.id.desc()).limit(limit).all())
        runs = {r.id: r for r in db.query(TaskRun).all()}
        for st in rows:
            run = runs.get(st.run_id)
            ok = st.status == "ok"
            items.append({
                "id": st.id,
                "ts": _fmt(st.finished_at or (st.created_at if hasattr(st, "created_at") else None)),
                "text": f"{run.name if run else '任务'} · 点位 {st.point_name or st.seq}"
                        f" {st.action or ''} {('正常' if ok else '失败')}"
                        + (f"：{st.error}" if st.error else ""),
                "level": "warn" if ok else "critical",
                "badge": "正常" if ok else "异常",
                "link": f"/task-runs?focus={st.run_id}",
            })

    else:  # control：审计里的设备/任务操作
        rows = (db.query(OperationLog)
                .filter(OperationLog.action.like("robot.%")
                        | OperationLog.action.like("task_run.%")
                        | OperationLog.action.like("work_order.%"))
                .order_by(OperationLog.ts.desc()).limit(limit).all())
        for op in rows:
            items.append({
                "id": op.id,
                "ts": _fmt(op.ts),
                "text": f"{op.username or '系统'} {op.action}"
                        + (f" · {op.target}" if op.target else ""),
                "level": "info",
                "badge": "成功" if op.success else "失败",
                "link": f"/oplog?focus={op.id}",
            })

    return {"kind": kind, "items": items}
