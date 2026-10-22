"""任务执行记录：平台建计划 + 机器人回传结果。

两条入口：
1. 平台侧 `POST /task-runs`：从模板生成一个"计划"（status=planned），**不下发**。
2. 机器人侧 `POST /task-runs/ingest`：真机执行完/执行中上报，按 external_id 幂等。

为什么要有 ingest 而不是只等平台推送：行业里机器人常常自己先跑（断网续跑），
平台事后补录比"必须先由平台下发"更符合现场。
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_csrf, require_roles
from app.services.api_auth import require_scope
from app.core.errors import BadRequest, NotFound
from app.db.session import get_db
from app.models.map_library import PointDraft
from app.models.task_run import TaskRun, TaskRunStep
from app.models.task_template import TaskTemplate
from app.models.user import User
from app.services.messages import audit

router = APIRouter(prefix="/task-runs", tags=["task-runs"])

STATUS_LABELS = {
    "planned": "计划中（未下发）",
    "running": "执行中",
    "done": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}


class RunIn(BaseModel):
    template_id: int | None = None
    robot_id: int | None = None
    name: str | None = None
    note: str | None = None


class StepIn(BaseModel):
    seq: int = 0
    point_id: int | None = None
    point_name: str | None = None
    action: str = "photo"
    status: str = "pending"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict | None = None
    error: str | None = None


class IngestIn(BaseModel):
    external_id: str = Field(min_length=1, max_length=64)
    robot_id: int | None = None
    name: str = ""
    status: str = "done"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    note: str | None = None
    steps: list[StepIn] = Field(default_factory=list)


def _run_out(r: TaskRun, steps: list[TaskRunStep] | None = None) -> dict:
    out = {
        "id": r.id, "name": r.name, "status": r.status,
        "status_label": STATUS_LABELS.get(r.status, r.status),
        "template_id": r.template_id, "robot_id": r.robot_id,
        "started_at": r.started_at.isoformat(timespec="seconds") if r.started_at else None,
        "finished_at": r.finished_at.isoformat(timespec="seconds") if r.finished_at else None,
        "created_at": r.created_at.isoformat(timespec="seconds") if r.created_at else None,
        "external_id": r.external_id, "note": r.note,
    }
    if steps is not None:
        ok = sum(1 for s in steps if s.status == "ok")
        out["progress"] = {"total": len(steps), "ok": ok,
                           "failed": sum(1 for s in steps if s.status == "failed")}
        out["steps"] = [
            {
                "id": s.id, "seq": s.seq, "point_id": s.point_id, "point_name": s.point_name,
                "action": s.action, "status": s.status,
                "started_at": s.started_at.isoformat(timespec="seconds") if s.started_at else None,
                "finished_at": s.finished_at.isoformat(timespec="seconds") if s.finished_at else None,
                "result": json.loads(s.result_json) if s.result_json else None,
                "error": s.error,
            }
            for s in sorted(steps, key=lambda x: x.seq)
        ]
    return out


@router.get("")
def list_runs(
    status: str | None = Query(None),
    robot_id: int | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    conds = []
    if status:
        conds.append(TaskRun.status == status)
    if robot_id:
        conds.append(TaskRun.robot_id == robot_id)
    q = select(TaskRun).order_by(TaskRun.id.desc()).limit(limit).offset(offset)
    cq = select(func.count()).select_from(TaskRun)
    if conds:
        from sqlalchemy import and_
        w = and_(*conds)
        q = q.where(w)
        cq = cq.where(w)
    rows = db.scalars(q).all()
    step_counts: dict[int, int] = {}
    for s in db.query(TaskRunStep).filter(TaskRunStep.run_id.in_([r.id for r in rows])).all():
        step_counts[s.run_id] = step_counts.get(s.run_id, 0) + 1
    return {
        "total": db.scalar(cq) or 0,
        "items": [{**_run_out(r), "step_count": step_counts.get(r.id, 0)} for r in rows],
    }


@router.get("/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db),
            _: User = Depends(get_current_user)) -> dict:
    r = db.get(TaskRun, run_id)
    if not r:
        raise NotFound("执行记录不存在")
    steps = db.query(TaskRunStep).filter(TaskRunStep.run_id == run_id).all()
    return _run_out(r, steps)


@router.post("", dependencies=[Depends(require_csrf)])
def create_run(
    body: RunIn,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "safety", "operator")),
) -> dict:
    """从模板生成一条计划（不下发）。"""
    name = (body.name or "").strip()
    steps: list[TaskRunStep] = []

    if body.template_id:
        t = db.get(TaskTemplate, body.template_id)
        if not t:
            raise NotFound("模板不存在")
        name = name or t.name
        try:
            actions = json.loads(t.actions_json or "[]")
        except Exception:  # noqa: BLE001
            actions = []
        names = {p.id: p.name for p in db.query(PointDraft).all()}
        for i, a in enumerate(actions):
            steps.append(TaskRunStep(
                run_id=0, seq=i + 1, point_id=a.get("point_id"),
                point_name=names.get(a.get("point_id")), action=a.get("action", "photo"),
                status="pending",
            ))
    if not name:
        raise BadRequest("要么给名称，要么给模板", code="NO_NAME")

    run = TaskRun(template_id=body.template_id, robot_id=body.robot_id,
                  name=name[:64], status="planned", note=body.note)
    db.add(run)
    db.flush()
    for s in steps:
        s.run_id = run.id
        db.add(s)
    db.commit()
    db.refresh(run)

    audit(db=db, action="task_run.create", target=run.name, user=me,
          detail={"template_id": body.template_id, "steps": len(steps)})
    return _run_out(run, steps)


@router.post("/ingest")
def ingest_run(
    body: IngestIn,
    db: Session = Depends(get_db),
    _client: dict = Depends(require_scope("task:ingest")),
) -> dict:
    """机器人回传执行结果。按 external_id 幂等：同一任务重复上报是"更新"，不是新增。"""
    status = body.status if body.status in STATUS_LABELS else "done"
    existing = db.query(TaskRun).filter(TaskRun.external_id == body.external_id).first()

    if existing:
        run = existing
        run.status = status
        run.finished_at = body.finished_at or run.finished_at
        run.note = body.note or run.note
        db.query(TaskRunStep).filter(TaskRunStep.run_id == run.id).delete()
        created = False
    else:
        run = TaskRun(
            name=(body.name or f"机器人任务 {body.external_id}")[:64],
            robot_id=body.robot_id, status=status, external_id=body.external_id,
            started_at=body.started_at, finished_at=body.finished_at, note=body.note,
        )
        db.add(run)
        db.flush()
        created = True

    for s in body.steps:
        db.add(TaskRunStep(
            run_id=run.id, seq=s.seq, point_id=s.point_id, point_name=s.point_name,
            action=s.action, status=s.status,
            started_at=s.started_at, finished_at=s.finished_at,
            result_json=json.dumps(s.result, ensure_ascii=False) if s.result else None,
            error=s.error,
        ))
    db.commit()
    db.refresh(run)
    steps = db.query(TaskRunStep).filter(TaskRunStep.run_id == run.id).all()
    return {**_run_out(run, steps), "created": created}


@router.post("/{run_id}/cancel", dependencies=[Depends(require_csrf)])
def cancel_run(
    run_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    """取消"计划中"的记录。已在执行的取消失败——那需要机器人急停/终止协议。"""
    r = db.get(TaskRun, run_id)
    if not r:
        raise NotFound("执行记录不存在")
    if r.status == "running":
        raise BadRequest("已经在下发了，平台无法单方面取消；请用机器人本体急停",
                         code="RUNNING_ON_ROBOT")
    if r.status != "planned":
        raise BadRequest(f"当前状态 {r.status} 不能取消", code="BAD_STATUS")
    r.status = "cancelled"
    db.commit()
    db.refresh(r)
    audit(db=db, action="task_run.cancel", target=r.name, user=me)
    return _run_out(r)
