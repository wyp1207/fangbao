"""云台控制接口（海康 ISAPI）。"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_csrf, require_roles
from app.core.errors import BadRequest
from app.db.session import get_db
from app.models.user import User
from app.services import ptz
from app.services.messages import audit

router = APIRouter(prefix="/ptz", tags=["ptz"])


@router.get("/status")
def ptz_status(_: User = Depends(require_roles("admin", "operator", "safety"))) -> dict:
    ok, detail = ptz.probe()
    return {"ok": ok, "detail": detail}


@router.post("/move", dependencies=[Depends(require_csrf)])
def ptz_move(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    direction = str(body.get("direction") or "").lower()
    if direction not in ("up", "down", "left", "right", "zoom_in", "zoom_out"):
        raise BadRequest("direction 只能是 up/down/left/right/zoom_in/zoom_out",
                         code="BAD_DIRECTION")
    ok, why = ptz.move(direction, speed=body.get("speed"), pulse_ms=int(body.get("pulse_ms") or 150))
    audit(db=db, action="ptz.move", target=direction, user=me,
          detail={"ok": ok, "reason": why or None, "pulse_ms": body.get("pulse_ms")})
    if not ok:
        raise BadRequest(f"云台指令失败：{why}", code="PTZ_FAILED")
    return {"ok": True, "direction": direction}


@router.post("/stop", dependencies=[Depends(require_csrf)])
def ptz_stop(
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    ok, why = ptz.stop()
    audit(db=db, action="ptz.stop", target="ptz", user=me, detail={"ok": ok})
    if not ok:
        raise BadRequest(f"云台停止失败：{why}", code="PTZ_FAILED")
    return {"ok": True}
