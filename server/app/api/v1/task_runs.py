"""任务执行记录：平台建计划 + 机器人回传结果。

两条入口：
1. 平台侧 `POST /task-runs`：从模板生成一个"计划"（status=planned），**不下发**。
2. 机器人侧 `POST /task-runs/ingest`：真机执行完/执行中上报，按 external_id 幂等。

为什么要有 ingest 而不是只等平台推送：行业里机器人常常自己先跑（断网续跑），
平台事后补录比"必须先由平台下发"更符合现场。
"""

from __future__ import annotations

import logging

import json
from datetime import datetime

from fastapi import Request, APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_csrf, require_roles
from app.services.api_auth import require_scope
from app.core.errors import BadRequest, NotFound, PlatformError
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
        "paused": bool(getattr(r, "paused_at", None)),
        "dispatched_at": r.dispatched_at.isoformat(timespec="seconds") if getattr(r, "dispatched_at", None) else None,
        "dispatch_error": getattr(r, "dispatch_error", None),
        "order_id": getattr(r, "order_id", None),
        "dispatch_state": getattr(r, "dispatch_state", None),
        "dispatch_attempt": getattr(r, "dispatch_attempt", None),
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
async def ingest_run(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """机器人回传执行结果。按 external_id 幂等：同一任务重复上报是"更新"，不是新增。

    鉴权两条路：带 X-Device-Key 走一机一密签名（含防重放）；不带则回退平台 API Key/会话。
    """
    from app.core.config import get_settings
    from app.services import device_auth
    from app.services.api_auth import session_or_key

    raw = await request.body()
    key_id = request.headers.get("X-Device-Key")
    if key_id:
        ok, why = device_auth.verify(
            db, key_id=key_id,
            ts=request.headers.get("X-Timestamp", ""),
            nonce=request.headers.get("X-Nonce", ""),
            signature=request.headers.get("X-Signature", ""),
            body=raw, secret=get_settings().secret_key,
        )
        if not ok:
            raise PlatformError("设备签名校验失败：%s" % why,
                                code="DEVICE_SIGNATURE", status_code=401)
    else:
        session_or_key(request=request, db=db)

    if len(raw) > 1024 * 1024:
        raise BadRequest("上报体超过 1MB", code="BODY_TOO_LARGE")
    try:
        body = IngestIn.model_validate_json(raw or b"{}")
    except Exception as exc:  # noqa: BLE001
        raise BadRequest("上报 JSON 格式错误：%s" % exc.__class__.__name__,
                         code="BAD_BODY") from exc
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


def _adapter_for(db: Session, run: TaskRun):
    from app.services.robot_runtime import registry as robot_registry

    rt = robot_registry.get(run.robot_id or 1)
    if rt is None or rt.adapter is None:
        raise BadRequest("该设备没有可用适配器（未启用或适配器未实现）", code="NO_ADAPTER")
    return rt.adapter


@router.post("/{run_id}/dispatch", dependencies=[Depends(require_csrf)])
def dispatch_run(
    run_id: int, db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    """下发到机器人。写开关关着时返回 403 WRITE_LOCKED 并说明缺什么。"""
    from app.services import task_dispatch

    run = db.get(TaskRun, run_id)
    if not run:
        raise NotFound("执行记录不存在")
    try:
        run = task_dispatch.dispatch(db, run, _adapter_for(db, run))
    except Exception as exc:  # noqa: BLE001
        run.dispatch_error = f"{exc.__class__.__name__}: {exc}"[:300]
        db.commit()
        log.exception("任务下发失败 run=%s", run_id)
        raise
    audit(db=db, action="task_run.dispatch", target=run.name, user=me,
          detail={"status": run.status, "external_id": run.external_id})
    return _run_out(run, db.query(TaskRunStep).filter(TaskRunStep.run_id == run.id).all())


@router.post("/{run_id}/steps/{seq}/retry", dependencies=[Depends(require_csrf)])
def retry_step(
    run_id: int, seq: int, db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    """重试某个点位的动作（拍照失败最常见）。只重做动作，不重新导航。"""
    from app.services.task_dispatch import _require_write

    _require_write()
    run = db.get(TaskRun, run_id)
    if not run:
        raise NotFound("执行记录不存在")
    step = (db.query(TaskRunStep)
            .filter(TaskRunStep.run_id == run_id, TaskRunStep.seq == seq).first())
    if not step:
        raise NotFound("点位不存在")

    adapter = _adapter_for(db, run)
    fn = getattr(adapter, "capture", None)
    if fn is None:
        raise BadRequest("适配器还没有取图接口，需真机确认抓拍 API", code="NO_CAPTURE")
    import asyncio

    try:
        res = fn(step)
        if hasattr(res, "__await__"):
            res = asyncio.run(res)
    except Exception as exc:  # noqa: BLE001
        step.error = f"重试失败：{exc.__class__.__name__}: {exc}"[:200]
        db.commit()
        raise BadRequest("重试失败，原因已记录", code="RETRY_FAILED") from exc

    step.status = "ok"
    step.error = None
    step.finished_at = datetime.now()
    step.result_json = json.dumps({"capture": res, "retried": True}, ensure_ascii=False)
    db.commit()
    audit(db=db, action="task_run.retry_step", target=f"{run.name}#{seq}", user=me)
    return {"ok": True, "seq": seq}


@router.post("/{run_id}/cruise", dependencies=[Depends(require_csrf)])
def start_cruise(
    run_id: int, from_seq: int = Body(0, embed=True), db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    """巡航：按点位顺序逐点下发、等到达、再下一个（平台侧状态机）。"""
    from app.services import cruise as cruise_mod
    from app.services.task_dispatch import _require_write

    _require_write()

    from app.services.task_lock import assert_free

    run = db.get(TaskRun, run_id)
    if run is not None:
        assert_free(db, run.robot_id, run.id)
    run = db.get(TaskRun, run_id)
    if not run:
        raise NotFound("执行记录不存在")
    if run.status not in ("planned", "failed", "cancelled"):
        raise BadRequest(f"当前状态 {run.status} 不能启动巡航", code="BAD_STATUS")
    if cruise_mod.runner is None:
        raise BadRequest("巡航执行器未启动", code="NO_RUNNER")

    adapter = _adapter_for(db, run)
    steps = db.query(TaskRunStep).filter(TaskRunStep.run_id == run.id).all()
    if not steps:
        raise BadRequest("这条计划没有点位", code="EMPTY_STEPS")

    from app.services.task_dispatch import preflight

    gate = preflight(db, run, adapter)
    if not gate["ok"]:
        raise PlatformError(gate["reason"], code="PREFLIGHT_FAILED", status_code=409)

    for s in steps:                     # 重跑时把旧结果清掉
        s.status = "pending"
        s.error = None
        s.finished_at = None
        s.result_json = None
    db.commit()

    cruise_mod.runner.start(run.id, adapter, from_seq=from_seq)
    audit(db=db, action="task_run.cruise", target=run.name, user=me,
          detail={"steps": len(steps)})
    return {"ok": True, "run_id": run.id, "steps": len(steps)}


@router.post("/{run_id}/cruise/cancel", dependencies=[Depends(require_csrf)])
def cancel_cruise(
    run_id: int, db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    from app.services import cruise as cruise_mod

    run = db.get(TaskRun, run_id)
    if not run:
        raise NotFound("执行记录不存在")
    adapter = _adapter_for(db, run)
    ok = cruise_mod.runner.cancel(run_id, adapter) if cruise_mod.runner else False
    audit(db=db, action="task_run.cruise_cancel", target=run.name, user=me)
    return {"ok": ok}


@router.get("/cruise/status")
def cruise_status(_: User = Depends(get_current_user)) -> dict:
    from app.services import cruise as cruise_mod

    running = cruise_mod.runner.running() if cruise_mod.runner else []
    return {"running": running}


@router.post("/{run_id}/pause", dependencies=[Depends(require_csrf)])
def pause_run(run_id: int, db: Session = Depends(get_db),
              me: User = Depends(require_roles("admin", "operator"))) -> dict:
    from app.services import task_dispatch

    run = db.get(TaskRun, run_id)
    if not run:
        raise NotFound("执行记录不存在")
    run = task_dispatch.pause(db, run, _adapter_for(db, run))
    audit(db=db, action="task_run.pause", target=run.name, user=me)
    return _run_out(run)


@router.post("/{run_id}/resume", dependencies=[Depends(require_csrf)])
def resume_run(run_id: int, db: Session = Depends(get_db),
               me: User = Depends(require_roles("admin", "operator"))) -> dict:
    from app.services import task_dispatch

    run = db.get(TaskRun, run_id)
    if not run:
        raise NotFound("执行记录不存在")
    run = task_dispatch.resume(db, run, _adapter_for(db, run))
    audit(db=db, action="task_run.resume", target=run.name, user=me)
    return _run_out(run)


@router.post("/{run_id}/cancel", dependencies=[Depends(require_csrf)])
def cancel_run(
    run_id: int,
    reason: str = Body("", embed=True),
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    """取消任务：计划中的直接作废；执行中的要机器人同意取消（写开关必须开）。"""
    from app.services import task_dispatch

    r = db.get(TaskRun, run_id)
    if not r:
        raise NotFound("执行记录不存在")

    if r.status == "planned":
        r.status = "cancelled"
        db.commit()
        db.refresh(r)
        audit(db=db, action="task_run.cancel", target=r.name, user=me,
          detail={"reason": (reason or "")[:200] or "未填原因"})
        return _run_out(r)

    if r.status != "running":
        raise BadRequest(f"当前状态 {r.status} 不能取消", code="BAD_STATUS")

    # 巡航是平台线程在逐点下发：必须先停线程，再让机器人取消当前目标
    from app.services import cruise as cruise_mod

    if cruise_mod.runner is not None:
        cruise_mod.runner.cancel(r.id, _adapter_for(db, r))
    r = task_dispatch.cancel(db, r, _adapter_for(db, r))
    audit(db=db, action="task_run.cancel", target=r.name, user=me, detail={"mode": "robot"})
    return _run_out(r)


log = logging.getLogger(__name__)
