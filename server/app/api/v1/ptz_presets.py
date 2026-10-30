"""云台预置位接口。"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_csrf, require_roles
from app.core.errors import BadRequest
from app.db.session import get_db
from app.models.user import User
from app.services import ptz_presets as presets
from app.services.messages import audit

router = APIRouter(prefix="/ptz/presets", tags=["ptz"])


@router.get("")
def list_presets(_: User = Depends(require_roles("admin", "operator", "safety"))) -> dict:
    ok, why, items = presets.list_presets()
    if not ok:
        return {"ok": False, "reason": why, "items": []}
    return {"ok": True, "items": items}


@router.post("", dependencies=[Depends(require_csrf)])
def save_preset(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    try:
        preset_id = int(body.get("preset_id"))
    except (TypeError, ValueError):
        raise BadRequest("preset_id 必须是数字", code="BAD_PRESET") from None
    name = str(body.get("name") or f"预置位 {preset_id}").strip()[:32]
    ok, why = presets.save_preset(preset_id, name)
    audit(db=db, action="ptz.preset_save", target=str(preset_id), user=me,
          detail={"name": name, "ok": ok})
    if not ok:
        raise BadRequest(f"保存预置位失败：{why}", code="PTZ_FAILED")
    return {"ok": True, "preset_id": preset_id, "name": name}


@router.post("/{preset_id}/goto", dependencies=[Depends(require_csrf)])
def goto_preset(
    preset_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    ok, why = presets.goto_preset(preset_id)
    audit(db=db, action="ptz.preset_goto", target=str(preset_id), user=me,
          detail={"ok": ok})
    if not ok:
        raise BadRequest(f"调用预置位失败：{why}", code="PTZ_FAILED")
    return {"ok": True, "preset_id": preset_id}


@router.delete("/{preset_id}", dependencies=[Depends(require_csrf)])
def delete_preset(
    preset_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    ok, why = presets.delete_preset(preset_id)
    audit(db=db, action="ptz.preset_delete", target=str(preset_id), user=me,
          detail={"ok": ok})
    if not ok:
        raise BadRequest(f"删除预置位失败：{why}", code="PTZ_FAILED")
    return {"ok": True, "preset_id": preset_id}
