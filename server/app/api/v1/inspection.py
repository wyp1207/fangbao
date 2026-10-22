"""人工巡检数字化 + 工单闭环。

对应客户方案 PPT 的模块三（人工数字化）和模块五（告警工单闭环）：
  计划派发 → 扫码打点 → 现场记录 → 缺陷上报 →（转工单）派单 → 处置 → 复核销号

设计取舍：
- 照片只存 URL/路径（走已有的 upload 目录），不在库里塞 base64
- "扫码打点" 用点位编号 code 校验：扫到的码必须和该项的 code 一致，
  否则记 scanned=False —— 防代签靠这个，不是靠界面自觉
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_csrf, require_roles
from app.core.errors import BadRequest, NotFound
from app.db.session import get_db
from app.models.inspection import InspectionItem, InspectionPlan, InspectionTask, WorkOrder
from app.models.user import User
from app.services.messages import audit

router = APIRouter(tags=["inspection"])

PHOTO_ROOT = Path(__file__).resolve().parents[3] / "data" / "inspection_photos"
ALLOWED_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_PHOTO = 6 * 1024 * 1024

TASK_STATUS = {"pending": "待执行", "doing": "执行中", "done": "已完成", "missed": "已超时"}
ORDER_STATUS = {
    "open": "待派单", "assigned": "已派单", "processing": "处置中",
    "review": "待复核", "closed": "已销号",
}
LEVELS = ("critical", "warn", "info")


def _items(raw: str | None) -> list:
    try:
        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except Exception:  # noqa: BLE001
        return []


# ---------------- 计划 ----------------

class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    station: str = "默认场站"
    shift: str = "早班"
    assignee_id: int | None = None
    items: list[dict] = Field(default_factory=list)
    enabled: bool = True
    note: str | None = None


def _plan_out(p: InspectionPlan) -> dict:
    items = _items(p.items_json)
    return {
        "id": p.id, "name": p.name, "station": p.station, "shift": p.shift,
        "assignee_id": p.assignee_id, "enabled": p.enabled, "note": p.note,
        "point_count": len(items), "items": items,
        "created_at": p.created_at.isoformat(timespec="seconds") if p.created_at else None,
    }


@router.get("/inspection/plans")
def list_plans(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[dict]:
    rows = db.query(InspectionPlan).order_by(InspectionPlan.id.desc()).all()
    return [_plan_out(p) for p in rows]


@router.post("/inspection/plans", dependencies=[Depends(require_csrf)])
def create_plan(
    body: PlanIn, db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "safety", "operator")),
) -> dict:
    if not body.items:
        raise BadRequest("至少配置一个巡检点位", code="EMPTY_ITEMS")
    for it in body.items:
        if not (it.get("name") or "").strip():
            raise BadRequest("点位名称不能为空", code="BAD_ITEM")
    p = InspectionPlan(
        name=body.name.strip(), station=body.station, shift=body.shift,
        assignee_id=body.assignee_id, enabled=body.enabled, note=body.note,
        items_json=json.dumps(body.items, ensure_ascii=False),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    audit(db=db, action="inspection_plan.create", target=p.name, user=me,
          detail={"points": len(body.items)})
    return _plan_out(p)


@router.patch("/inspection/plans/{plan_id}", dependencies=[Depends(require_csrf)])
def update_plan(
    plan_id: int, body: dict, db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "safety", "operator")),
) -> dict:
    p = db.get(InspectionPlan, plan_id)
    if not p:
        raise NotFound("计划不存在")
    if "items" in body and body["items"] is not None:
        p.items_json = json.dumps(body["items"], ensure_ascii=False)
    for k in ("name", "station", "shift", "assignee_id", "enabled", "note"):
        if k in body and body[k] is not None:
            setattr(p, k, body[k])
    db.commit()
    db.refresh(p)
    audit(db=db, action="inspection_plan.update", target=p.name, user=me)
    return _plan_out(p)


@router.delete("/inspection/plans/{plan_id}", dependencies=[Depends(require_csrf)])
def delete_plan(
    plan_id: int, db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    p = db.get(InspectionPlan, plan_id)
    if not p:
        raise NotFound("计划不存在")
    db.delete(p)
    db.commit()
    audit(db=db, action="inspection_plan.delete", target=p.name, user=me)
    return {"ok": True}


# ---------------- 任务 ----------------

class GenerateIn(BaseModel):
    plan_id: int
    due_hours: int = 8
    assignee_id: int | None = None


class TaskOut(BaseModel):
    pass


def _task_out(t: InspectionTask, items: list[InspectionItem] | None = None) -> dict:
    out = {
        "id": t.id, "title": t.title, "plan_id": t.plan_id, "assignee_id": t.assignee_id,
        "status": t.status, "status_label": TASK_STATUS.get(t.status, t.status),
        "due_at": t.due_at.isoformat(timespec="minutes") if t.due_at else None,
        "started_at": t.started_at.isoformat(timespec="minutes") if t.started_at else None,
        "finished_at": t.finished_at.isoformat(timespec="minutes") if t.finished_at else None,
        "created_at": t.created_at.isoformat(timespec="minutes") if t.created_at else None,
        "note": t.note,
    }
    if items is not None:
        done = sum(1 for i in items if i.result in ("ok", "abnormal"))
        out["progress"] = {
            "total": len(items), "done": done,
            "abnormal": sum(1 for i in items if i.result == "abnormal"),
        }
        out["items"] = [
            {
                "id": i.id, "seq": i.seq, "point_id": i.point_id, "point_name": i.point_name,
                "code": i.code, "checks": _items(i.checks_json), "result": i.result,
                "note": i.note, "photos": _items(i.photos_json),
                "scanned_at": i.scanned_at.isoformat(timespec="seconds") if i.scanned_at else None,
                "checked_at": i.checked_at.isoformat(timespec="seconds") if i.checked_at else None,
            }
            for i in sorted(items, key=lambda x: x.seq)
        ]
    return out


@router.post("/inspection/tasks/generate", dependencies=[Depends(require_csrf)])
def generate_tasks(
    body: GenerateIn, db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "safety", "operator")),
) -> dict:
    plan = db.get(InspectionPlan, body.plan_id)
    if not plan:
        raise NotFound("计划不存在")
    if not plan.enabled:
        raise BadRequest("计划已停用", code="PLAN_DISABLED")
    items = _items(plan.items_json)
    if not items:
        raise BadRequest("计划里没有点位", code="EMPTY_ITEMS")

    title = f"{plan.name} · {datetime.now().strftime('%m-%d')} {plan.shift}"
    task = InspectionTask(
        plan_id=plan.id, title=title[:64],
        assignee_id=body.assignee_id or plan.assignee_id,
        due_at=datetime.now() + timedelta(hours=body.due_hours),
        status="pending",
    )
    db.add(task)
    db.flush()
    for idx, it in enumerate(items, start=1):
        db.add(InspectionItem(
            task_id=task.id, seq=idx, point_id=it.get("point_id"),
            point_name=(it.get("name") or f"点位{idx}")[:64],
            code=it.get("code"),
            checks_json=json.dumps(it.get("checks") or [], ensure_ascii=False),
        ))
    db.commit()
    db.refresh(task)
    rows = db.query(InspectionItem).filter(InspectionItem.task_id == task.id).all()
    audit(db=db, action="inspection_task.generate", target=title, user=me,
          detail={"plan_id": plan.id})
    return _task_out(task, rows)


@router.get("/inspection/tasks")
def list_tasks(
    status: str | None = Query(None),
    mine: bool = Query(False),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
) -> dict:
    conds = []
    if status:
        conds.append(InspectionTask.status == status)
    if mine:
        conds.append(InspectionTask.assignee_id == me.id)
    q = select(InspectionTask).order_by(InspectionTask.id.desc()).limit(limit)
    cq = select(func.count()).select_from(InspectionTask)
    if conds:
        from sqlalchemy import and_
        w = and_(*conds)
        q = q.where(w)
        cq = cq.where(w)
    rows = db.scalars(q).all()
    counts: dict[int, int] = {}
    done: dict[int, int] = {}
    for it in db.query(InspectionItem).filter(
        InspectionItem.task_id.in_([r.id for r in rows] or [0])
    ).all():
        counts[it.task_id] = counts.get(it.task_id, 0) + 1
        if it.result in ("ok", "abnormal"):
            done[it.task_id] = done.get(it.task_id, 0) + 1
    return {
        "total": db.scalar(cq) or 0,
        "items": [
            {**_task_out(r), "item_count": counts.get(r.id, 0), "done_count": done.get(r.id, 0)}
            for r in rows
        ],
    }


@router.get("/inspection/tasks/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db),
             _: User = Depends(get_current_user)) -> dict:
    t = db.get(InspectionTask, task_id)
    if not t:
        raise NotFound("任务不存在")
    rows = db.query(InspectionItem).filter(InspectionItem.task_id == task_id).all()
    return _task_out(t, rows)


class CheckIn(BaseModel):
    result: str = Field(pattern="^(ok|abnormal|skipped)$")
    code: str | None = None            # 扫到的码，用来校验是否真的到点
    note: str | None = None
    photos: list[str] = Field(default_factory=list)
    checks_done: list[str] = Field(default_factory=list)


@router.post("/inspection/tasks/{task_id}/items/{item_id}/check", dependencies=[Depends(require_csrf)])
def check_item(
    task_id: int, item_id: int, body: CheckIn,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "safety", "operator")),
) -> dict:
    item = db.get(InspectionItem, item_id)
    if not item or item.task_id != task_id:
        raise NotFound("巡检项不存在")
    task = db.get(InspectionTask, task_id)
    if not task:
        raise NotFound("任务不存在")
    if task.status == "done":
        raise BadRequest("任务已完成，不能再改", code="TASK_DONE")

    now = datetime.now()
    if item.code and body.code is not None:
        # 扫码防代签：码不对就记"未扫码"，但不拦提交（现场可能码牌破损）
        if body.code.strip() != item.code.strip():
            raise BadRequest(f"扫码编号不匹配：点位要求 {item.code}", code="BAD_CODE")
        item.scanned_at = now

    item.result = body.result
    item.note = body.note
    item.photos_json = json.dumps(body.photos, ensure_ascii=False)
    item.checked_at = now
    if body.checks_done:
        item.checks_json = json.dumps(body.checks_done, ensure_ascii=False)

    if task.status == "pending":
        task.status = "doing"
        task.started_at = task.started_at or now

    db.commit()
    db.refresh(item)
    rows = db.query(InspectionItem).filter(InspectionItem.task_id == task_id).all()
    audit(db=db, action="inspection_item.check", target=f"{task.title}/{item.point_name}",
          user=me, detail={"result": body.result, "scanned": bool(item.scanned_at)})
    return {
        "item": {"id": item.id, "result": item.result, "scanned": bool(item.scanned_at)},
        "task": _task_out(task, rows),
    }


@router.post("/inspection/tasks/{task_id}/items/{item_id}/photo", dependencies=[Depends(require_csrf)])
def upload_photo(
    task_id: int, item_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "safety", "operator")),
) -> dict:
    """现场拍照上传：只收图片、限 6MB、按日期分目录存，库里只存相对路径。"""
    item = db.get(InspectionItem, item_id)
    if not item or item.task_id != task_id:
        raise NotFound("巡检项不存在")

    ext = ALLOWED_TYPES.get(file.content_type or "")
    if ext is None:
        raise BadRequest("只支持 JPG/PNG/WebP", code="BAD_IMAGE_TYPE")
    data = file.file.read(MAX_PHOTO + 1)
    if len(data) > MAX_PHOTO:
        raise BadRequest("图片超过 6MB，请压缩后再传", code="IMAGE_TOO_LARGE")

    day = datetime.now().strftime("%Y%m%d")
    name = f"{day}/{uuid4().hex}{ext}"
    (PHOTO_ROOT / day).mkdir(parents=True, exist_ok=True)
    (PHOTO_ROOT / name).write_bytes(data)

    photos = _items(item.photos_json)
    photos.append(f"inspection_photos/{name}")
    item.photos_json = json.dumps(photos, ensure_ascii=False)
    db.commit()
    audit(db=db, action="inspection.photo", target=item.point_name, user=me,
          detail={"size": len(data), "count": len(photos)})
    return {"ok": True, "url": f"/api/v1/inspection/photos/{name}", "count": len(photos)}


@router.get("/inspection/photos/{path:path}")
def get_photo(path: str, _: User = Depends(get_current_user)):
    from fastapi.responses import FileResponse

    target = (PHOTO_ROOT / path).resolve()
    if not str(target).startswith(str(PHOTO_ROOT.resolve())) or not target.exists():
        raise NotFound("图片不存在")
    return FileResponse(target)


@router.post("/inspection/tasks/{task_id}/finish", dependencies=[Depends(require_csrf)])
def finish_task(
    task_id: int, db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "safety", "operator")),
) -> dict:
    t = db.get(InspectionTask, task_id)
    if not t:
        raise NotFound("任务不存在")
    rows = db.query(InspectionItem).filter(InspectionItem.task_id == task_id).all()
    left = [r.point_name for r in rows if r.result == "pending"]
    if left:
        raise BadRequest(f"还有 {len(left)} 个点位没打点：{', '.join(left[:3])}", code="ITEMS_LEFT")
    t.status = "done"
    t.finished_at = datetime.now()
    db.commit()
    db.refresh(t)
    audit(db=db, action="inspection_task.finish", target=t.title, user=me)
    return _task_out(t, rows)


# ---------------- 工单 ----------------

class OrderIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    source: str = "manual"
    source_id: int | None = None
    level: str = "warn"
    assignee_id: int | None = None
    due_hours: int = 24
    description: str | None = None
    photos: list[str] = Field(default_factory=list)


class OrderUpdate(BaseModel):
    status: str | None = None
    assignee_id: int | None = None
    resolution: str | None = None
    due_hours: int | None = None


def _mobile_url(o: WorkOrder) -> str:
    from app.core.config import get_settings

    base = (get_settings().public_base_url or "").rstrip("/")
    return f"{base}/m/wo/{o.id}" if base else f"/m/wo/{o.id}"


def _push_to_assignee(db: Session, o: WorkOrder) -> None:
    """有责任人就推一条到通知通道（企业微信/钉钉/Webhook），带手机链接。"""
    from app.models.user import User as _User
    from app.services.notify import push_text

    uid = o.assignee_id
    if not uid:
        return
    user = db.get(_User, uid)
    if user is None:
        return
    push_text(
        f"工单 {o.code or ''}：{o.title}\n"
        f"责任人：{user.username}\n限时：{o.due_at.strftime('%m-%d %H:%M') if o.due_at else '未设'}\n"
        f"手机处理：{_mobile_url(o)}",
        level=o.level,
    )


def _order_out(o: WorkOrder) -> dict:
    return {
        "id": o.id, "code": o.code, "title": o.title, "source": o.source,
        "source_id": o.source_id, "level": o.level, "status": o.status,
        "status_label": ORDER_STATUS.get(o.status, o.status),
        "assignee_id": o.assignee_id,
        "due_at": o.due_at.isoformat(timespec="minutes") if o.due_at else None,
        "description": o.description, "photos": _items(o.photos_json),
        "resolution": o.resolution,
        "escalated_at": o.escalated_at.isoformat(timespec="minutes") if o.escalated_at else None,
        "created_at": o.created_at.isoformat(timespec="minutes") if o.created_at else None,
        "closed_at": o.closed_at.isoformat(timespec="minutes") if o.closed_at else None,
        "mobile_url": _mobile_url(o),
    }


@router.get("/work-orders")
def list_orders(
    status: str | None = Query(None),
    assignee_id: int | None = Query(None),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    q = select(WorkOrder).order_by(WorkOrder.id.desc()).limit(limit)
    cq = select(func.count()).select_from(WorkOrder)
    if status:
        q = q.where(WorkOrder.status == status)
        cq = cq.where(WorkOrder.status == status)
    if assignee_id:
        q = q.where(WorkOrder.assignee_id == assignee_id)
        cq = cq.where(WorkOrder.assignee_id == assignee_id)
    rows = db.scalars(q).all()
    return {"total": db.scalar(cq) or 0, "items": [_order_out(o) for o in rows]}


@router.get("/work-orders/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db),
              _: User = Depends(get_current_user)) -> dict:
    o = db.get(WorkOrder, order_id)
    if not o:
        raise NotFound("工单不存在")
    return _order_out(o)


@router.post("/work-orders", dependencies=[Depends(require_csrf)])
def create_order(
    body: OrderIn, db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "safety", "operator")),
) -> dict:
    if body.level not in LEVELS:
        raise BadRequest(f"等级只能是 {LEVELS}", code="BAD_LEVEL")
    seq = (db.scalar(select(func.count()).select_from(WorkOrder)) or 0) + 1
    o = WorkOrder(
        code=f"WO-{datetime.now().strftime('%Y%m%d')}-{seq:03d}",
        title=body.title.strip()[:120], source=body.source, source_id=body.source_id,
        level=body.level, assignee_id=body.assignee_id,
        due_at=datetime.now() + timedelta(hours=body.due_hours),
        description=body.description,
        photos_json=json.dumps(body.photos, ensure_ascii=False),
        status="assigned" if body.assignee_id else "open",
    )
    db.add(o)
    db.commit()
    db.refresh(o)
    audit(db=db, action="work_order.create", target=o.code or str(o.id), user=me,
          detail={"level": o.level, "assignee": o.assignee_id})
    if o.assignee_id:
        _push_to_assignee(db, o)
    return _order_out(o)


class AssignIn(BaseModel):
    assignee_id: int
    due_hours: int | None = None


@router.post("/work-orders/{order_id}/assign", dependencies=[Depends(require_csrf)])
def assign_order(
    order_id: int, body: AssignIn, db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "safety", "operator")),
) -> dict:
    o = db.get(WorkOrder, order_id)
    if not o:
        raise NotFound("工单不存在")
    o.assignee_id = body.assignee_id
    o.status = "assigned"
    if body.due_hours:
        o.due_at = datetime.now() + timedelta(hours=body.due_hours)
    db.commit()
    db.refresh(o)
    audit(db=db, action="work_order.assign", target=o.code or str(o.id), user=me,
          detail={"assignee": body.assignee_id})
    _push_to_assignee(db, o)
    return _order_out(o)


@router.post("/work-orders/{order_id}/transition", dependencies=[Depends(require_csrf)])
def transition_order(
    order_id: int, body: OrderUpdate, db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "safety", "operator")),
) -> dict:
    """处置回填 → 提交复核 → 复核销号。跳步会被拦。"""
    o = db.get(WorkOrder, order_id)
    if not o:
        raise NotFound("工单不存在")

    target = body.status
    if target is None:
        raise BadRequest("缺少目标状态", code="NO_STATUS")
    allowed = {
        "open": {"assigned", "processing"},
        "assigned": {"processing"},
        "processing": {"review"},
        "review": {"closed", "processing"},
        "closed": set(),
    }
    if target not in allowed.get(o.status, set()):
        raise BadRequest(
            f"不能从「{ORDER_STATUS.get(o.status)}」直接到「{ORDER_STATUS.get(target)}」",
            code="BAD_TRANSITION",
        )
    if target == "closed" and not (body.resolution or o.resolution):
        raise BadRequest("销号必须填处置结果", code="NO_RESOLUTION")

    if body.resolution:
        o.resolution = body.resolution
    if body.assignee_id:
        o.assignee_id = body.assignee_id
    o.status = target
    if target == "closed":
        o.closed_at = datetime.now()
    db.commit()
    db.refresh(o)
    audit(db=db, action=f"work_order.{target}", target=o.code or str(o.id), user=me)
    return _order_out(o)


@router.post("/work-orders/{order_id}/photo", dependencies=[Depends(require_csrf)])
def upload_order_photo(
    order_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "safety", "operator")),
) -> dict:
    """现场核实拍照：手机上拍完直接传，作为处置证据。"""
    o = db.get(WorkOrder, order_id)
    if not o:
        raise NotFound("工单不存在")
    ext = ALLOWED_TYPES.get(file.content_type or "")
    if ext is None:
        raise BadRequest("只支持 JPG/PNG/WebP", code="BAD_IMAGE_TYPE")
    data = file.file.read(MAX_PHOTO + 1)
    if len(data) > MAX_PHOTO:
        raise BadRequest("图片超过 6MB，请压缩后再传", code="IMAGE_TOO_LARGE")

    day = datetime.now().strftime("%Y%m%d")
    name = f"wo-{day}/{uuid4().hex}{ext}"
    (PHOTO_ROOT / f"wo-{day}").mkdir(parents=True, exist_ok=True)
    (PHOTO_ROOT / name).write_bytes(data)

    photos = _items(o.photos_json)
    photos.append(f"inspection_photos/{name}")
    o.photos_json = json.dumps(photos, ensure_ascii=False)
    db.commit()
    audit(db=db, action="work_order.photo", target=o.code or str(o.id), user=me,
          detail={"count": len(photos), "size": len(data)})
    return {"ok": True, "url": f"/api/v1/inspection/photos/{name}", "count": len(photos)}


@router.post("/work-orders/{order_id}/escalate", dependencies=[Depends(require_csrf)])
def escalate_order(
    order_id: int, db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "safety", "operator")),
) -> dict:
    """超时未处置 → 升级（记 escalated_at，并由外发通道通知值班长）。"""
    from app.services.messages import store as msg_store

    o = db.get(WorkOrder, order_id)
    if not o:
        raise NotFound("工单不存在")
    if o.status in ("closed",):
        raise BadRequest("已销号的工单不用升级", code="ALREADY_CLOSED")
    o.escalated_at = datetime.now()
    if o.level != "critical":
        o.level = "warn"
    db.commit()
    db.refresh(o)
    msg_store.add("warn", "work_order", f"工单升级：{o.title}",
                  f"{o.code} 超过期限未处置，已上报值班长", {"to": "work-orders"})
    audit(db=db, action="work_order.escalate", target=o.code or str(o.id), user=me)
    return _order_out(o)
