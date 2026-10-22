"""巡检任务模板：平台侧草稿 CRUD。

明确不做的事：**不发下**。`POST /task-templates/{id}/dispatch` 返回 501
并说明缺什么（真机联调 + 现场授权），不做假成功。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_csrf, require_roles
from app.core.errors import BadRequest, NotFound
from app.db.session import get_db
from app.models.map_library import PlatformMap, PointDraft
from app.models.task_template import TaskTemplate
from app.models.user import User
from app.services.messages import audit

router = APIRouter(prefix="/task-templates", tags=["task-templates"])

# 只允许协议里确认过的动作，避免前端随便传个字符串就存进去
ACTIONS = {
    "photo": "拍照",
    "video": "录像片段",
    "wait": "停留",
    "ptz": "云台转向",
    "thermal": "热成像采集",
}


class ActionIn(BaseModel):
    point_id: int
    action: str
    params: dict = Field(default_factory=dict)


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    map_id: int | None = None
    robot_id: int | None = None
    actions: list[ActionIn] = Field(default_factory=list)
    loop: bool = False
    note: str | None = None


def _out(t: TaskTemplate, point_names: dict[int, str] | None = None) -> dict:
    try:
        actions = json.loads(t.actions_json or "[]")
    except Exception:  # noqa: BLE001
        actions = []
    return {
        "id": t.id, "name": t.name, "map_id": t.map_id, "robot_id": t.robot_id,
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
def list_templates(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[dict]:
    names = {p.id: p.name for p in db.query(PointDraft).all()}
    return [_out(t, names) for t in db.query(TaskTemplate).order_by(TaskTemplate.id.desc()).all()]


@router.post("", dependencies=[Depends(require_csrf)])
def create_template(
    body: TemplateIn,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "safety", "operator")),
) -> dict:
    _validate_points(db, body)
    t = TaskTemplate(
        name=body.name, map_id=body.map_id, robot_id=body.robot_id,
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

    for k in ("name", "map_id", "robot_id", "loop", "note"):
        if k in body and body[k] is not None:
            setattr(t, k, body[k])
    db.commit()
    db.refresh(t)
    audit(db=db, action="task_template.update", target=t.name, user=me)
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
    _: User = Depends(require_roles("admin")),
) -> dict:
    """下发到机器人：真机联调 + 现场授权后才开放。现在明确拒绝。"""
    raise HTTPException(
        status_code=501,
        detail="任务下发需要机器人写权限：等真机到场联调 + 现场授权签字后开放。"
               "现在可以在模板里把点位和动作配好，届时一键下发。",
    )
