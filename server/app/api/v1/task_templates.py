"""巡检任务模板：平台侧草稿 CRUD。

明确不做的事：**不发下**。`POST /task-templates/{id}/dispatch` 返回 501
并说明缺什么（真机联调 + 现场授权），不做假成功。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_csrf, require_roles
from app.core.errors import BadRequest, NotFound, PlatformError
from app.db.session import get_db
from app.models.map_library import PlatformMap, PointDraft
from app.models.robot import Robot
from app.models.task_run import TaskRun, TaskRunStep
from app.models.task_template import TaskTemplate
from app.models.user import User
from app.services.messages import audit
from app.services.sites import assert_no_cross_site, resolve_site_id

router = APIRouter(prefix="/task-templates", tags=["task-templates"])

# 只允许协议里确认过的动作，避免前端随便传个字符串就存进去
ACTIONS = {
    "photo": "拍照",
    "video": "录像片段",
    "wait": "停留",
    "ptz": "云台转向",
    "thermal": "热成像采集",
    "thermal_temp": "测温（红外点温）",
}


class ActionIn(BaseModel):
    point_id: int
    action: str
    params: dict = Field(default_factory=dict)


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    map_id: int | None = None
    site_id: int | None = None
    # 旧字段：语义降级为“默认设备”，仅为兼容旧前端保留
    robot_id: int | None = None
    default_robot_id: int | None = None
    actions: list[ActionIn] = Field(default_factory=list)
    loop: bool = False
    note: str | None = None


def _default_robot_id(body: TemplateIn) -> int | None:
    """default_robot_id 是新名字；老前端仍传 robot_id 时按默认设备处理。"""
    return body.default_robot_id if body.default_robot_id is not None else body.robot_id


def _out(t: TaskTemplate, point_names: dict[int, str] | None = None) -> dict:
    try:
        actions = json.loads(t.actions_json or "[]")
    except Exception:  # noqa: BLE001
        actions = []
    return {
        "id": t.id, "name": t.name, "map_id": t.map_id, "site_id": t.site_id,
        # 同一列两个名字：新代码用 default_robot_id，旧前端继续读 robot_id
        "robot_id": t.robot_id, "default_robot_id": t.robot_id,
        "loop": t.loop, "note": t.note,
        "actions": actions,
        "action_count": len(actions),
        "summary": " → ".join(
            (point_names or {}).get(a.get("point_id"), f"#{a.get('point_id')}")
            + f"({ACTIONS.get(a.get('action'), a.get('action'))})"
            for a in actions
        ),
        "created_at": t.created_at.isoformat(timespec="seconds") if t.created_at else None,
    }


def _validate_points(db: Session, body: TemplateIn) -> None:
    if body.map_id is not None and not db.get(PlatformMap, body.map_id):
        raise BadRequest("地图不存在", code="NO_MAP")
    if not body.actions:
        raise BadRequest("至少要有一个点位动作", code="EMPTY_ACTIONS")

    ids = [a.point_id for a in body.actions]
    if len(set(ids)) != len(ids):
        raise BadRequest("同一个点位不能重复出现两次", code="DUP_POINT")

    rows = db.query(PointDraft).filter(PointDraft.id.in_(ids)).all()
    found = {r.id: r for r in rows}
    missing = [i for i in ids if i not in found]
    if missing:
        raise BadRequest(f"点位不存在：{missing}", code="NO_POINT")
    wrong_map = [r.id for r in rows if body.map_id is not None and r.map_id != body.map_id]
    if wrong_map:
        raise BadRequest(f"这些点位不属于所选地图：{wrong_map}", code="POINT_MISMATCH")

    for a in body.actions:
        if a.action not in ACTIONS:
            raise BadRequest(f"未知动作 {a.action}，可用：{', '.join(ACTIONS)}", code="BAD_ACTION")


@router.get("/meta")
def meta(_: User = Depends(get_current_user)) -> dict:
    return {"actions": [{"value": k, "label": v} for k, v in ACTIONS.items()]}


@router.get("")
def list_templates(
    site_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    names = {p.id: p.name for p in db.query(PointDraft).all()}
    q = db.query(TaskTemplate)
    if site_id is not None:
        q = q.filter(TaskTemplate.site_id == site_id)
    return [_out(t, names) for t in q.order_by(TaskTemplate.id.desc()).all()]


@router.post("", dependencies=[Depends(require_csrf)])
def create_template(
    body: TemplateIn,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "safety", "operator")),
) -> dict:
    _validate_points(db, body)
    robot_id = _default_robot_id(body)
    # site 必须由 map 推导；显式传了不一致的 site、或默认设备不在同站，直接 409
    site_id = resolve_site_id(db, map_id=body.map_id, site_id=body.site_id,
                              robot_id=robot_id)
    t = TaskTemplate(
        name=body.name, map_id=body.map_id, site_id=site_id, robot_id=robot_id,
        actions_json=json.dumps([a.model_dump() for a in body.actions], ensure_ascii=False),
        loop=body.loop, note=body.note,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    audit(db=db, action="task_template.create", target=t.name, user=me,
          detail={"actions": len(body.actions), "map_id": body.map_id})
    return _out(t)


@router.patch("/{template_id}", dependencies=[Depends(require_csrf)])
def update_template(
    template_id: int,
    body: dict,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "safety", "operator")),
) -> dict:
    t = db.get(TaskTemplate, template_id)
    if not t:
        raise NotFound("模板不存在")

    if "actions" in body and body["actions"] is not None:
        try:
            payload = TemplateIn(
                name=body.get("name") or t.name,
                map_id=body.get("map_id", t.map_id),
                actions=[ActionIn(**a) for a in body["actions"]],
            )
        except Exception as exc:  # noqa: BLE001
            raise BadRequest(f"动作格式不对：{exc}", code="BAD_ACTIONS") from exc
        _validate_points(db, payload)
        t.actions_json = json.dumps([a.model_dump() for a in payload.actions], ensure_ascii=False)

    # 归属相关字段变了才重新推导，避免只改名字也被历史脏数据绊住
    new_robot_id = t.robot_id
    if "default_robot_id" in body:
        new_robot_id = body["default_robot_id"]
    elif "robot_id" in body:
        new_robot_id = body["robot_id"]
    new_map_id = body["map_id"] if "map_id" in body else t.map_id
    if "map_id" in body or "site_id" in body or "robot_id" in body or "default_robot_id" in body:
        t.site_id = resolve_site_id(
            db, map_id=new_map_id,
            site_id=body["site_id"] if "site_id" in body else None,
            robot_id=new_robot_id, current=t.site_id,
        )
        t.map_id = new_map_id
        t.robot_id = new_robot_id

    for k in ("name", "loop", "note"):
        if k in body and body[k] is not None:
            setattr(t, k, body[k])
    db.commit()
    db.refresh(t)
    audit(db=db, action="task_template.update", target=t.name, user=me)
    return _out(t)


@router.post("/{template_id}/duplicate", dependencies=[Depends(require_csrf)])
def duplicate_template(
    template_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "safety", "operator")),
) -> dict:
    src = db.get(TaskTemplate, template_id)
    if not src:
        raise NotFound("模板不存在")
    suffix = " 副本"
    name = (src.name + suffix)[:64]
    n = 2
    while db.query(TaskTemplate).filter(TaskTemplate.name == name).first():
        name = f"{src.name} 副本{n}"[:64]
        n += 1
    t = TaskTemplate(name=name, map_id=src.map_id, site_id=src.site_id,
                     robot_id=src.robot_id,
                     actions_json=src.actions_json, loop=src.loop, note=src.note)
    db.add(t)
    db.commit()
    db.refresh(t)
    audit(db=db, action="task_template.duplicate", target=t.name, user=me,
          detail={"from": src.id})
    return _out(t)


@router.delete("/{template_id}", dependencies=[Depends(require_csrf)])
def delete_template(
    template_id: int, db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    t = db.get(TaskTemplate, template_id)
    if not t:
        raise NotFound("模板不存在")
    db.delete(t)
    db.commit()
    audit(db=db, action="task_template.delete", target=t.name, user=me)
    return {"ok": True}


@router.post("/{template_id}/dispatch", dependencies=[Depends(require_csrf)])
def dispatch_template(
    template_id: int,
    robot_id: int | None = Body(None, embed=True),
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    """从模板直接创建执行记录并下发（写开关仍然把关）。

    模板不再强制绑定设备：可以传 robot_id，也可以用模板的 default_robot_id。
    真正拦人的是场站一致性——模板/地图/设备三者场站不一致时 409 CROSS_SITE。
    """
    from app.services import task_dispatch

    tpl = db.get(TaskTemplate, template_id)
    if tpl is None:
        raise NotFound("模板不存在")

    target_robot_id = robot_id if robot_id is not None else tpl.robot_id
    if not target_robot_id:
        raise BadRequest("模板没绑定默认设备，先选设备或传 robot_id", code="NO_ROBOT")
    robot = db.get(Robot, int(target_robot_id))
    if robot is None:
        raise BadRequest(f"设备不存在：{target_robot_id}", code="NO_ROBOT")

    map_row = db.get(PlatformMap, tpl.map_id) if tpl.map_id else None
    map_site = map_row.site_id if map_row is not None else None
    tpl_site = tpl.site_id if tpl.site_id is not None else map_site
    run_site = robot.site_id if robot.site_id is not None else tpl_site
    assert_no_cross_site(run_site=run_site, robot_site=robot.site_id,
                         map_site=map_site, template_site=tpl_site)

    actions = json.loads(tpl.actions_json or "[]")
    names = {p.id: p.name for p in db.query(PointDraft).all()}
    run = TaskRun(template_id=tpl.id, robot_id=robot.id, site_id=run_site,
                  map_id=tpl.map_id, name=tpl.name[:64], status="planned")
    db.add(run)
    db.flush()
    for i, a in enumerate(actions):
        db.add(TaskRunStep(run_id=run.id, seq=i + 1, point_id=a.get("point_id"),
                           point_name=names.get(a.get("point_id")),
                           action=a.get("action", "photo"), status="pending"))
    from app.services.task_events import safe_log

    safe_log(db, run.id, "created", f"由模板「{tpl.name}」创建执行计划",
             data={"template_id": tpl.id, "steps": len(actions)}, actor=me.username)
    db.commit()
    db.refresh(run)

    from app.api.v1.task_runs import _adapter_for

    run = task_dispatch.dispatch(db, run, _adapter_for(db, run))
    audit(db=db, action="task_template.dispatch", target=tpl.name, user=me,
          detail={"run_id": run.id, "status": run.status})
    return {"ok": True, "run_id": run.id, "status": run.status}
