"""录制计划：CRUD + 调度。

调度器只负责"到点开关"，不碰录像文件本身。
为避免和手动录制互相打架：只有**由计划启动**的录制才会被计划停掉，
手动开的录制不会因为窗口结束被关掉。
"""

from __future__ import annotations

import logging
import threading
import time as _time
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_csrf, require_roles
from app.core.errors import BadRequest, NotFound
from app.db.session import get_db
from app.models.record_plan import RecordPlan
from app.models.user import User
from app.models.video_source import VideoSource
from app.services.messages import audit
from app.services.recorder import registry

log = logging.getLogger(__name__)
router = APIRouter(prefix="/record-plans", tags=["record-plans"])

_started_by_plan: set[int] = set()


class PlanIn(BaseModel):
    video_id: int
    name: str = Field(min_length=1, max_length=64)
    days: str = Field(default="1111111", min_length=7, max_length=7)
    start_time: str = Field(default="00:00", pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(default="23:59", pattern=r"^\d{2}:\d{2}$")
    enabled: bool = True
    note: str | None = None


def _out(p: RecordPlan, video_name: str = "") -> dict:
    return {
        "id": p.id, "video_id": p.video_id, "video_name": video_name,
        "name": p.name, "days": p.days, "start_time": p.start_time,
        "end_time": p.end_time, "enabled": p.enabled, "note": p.note,
        "active_now": p.in_window(datetime.now()),
    }


@router.get("")
def list_plans(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[dict]:
    names = {v.id: v.name for v in db.query(VideoSource).all()}
    return [_out(p, names.get(p.video_id, f"#{p.video_id}"))
            for p in db.query(RecordPlan).order_by(RecordPlan.id).all()]


@router.post("", dependencies=[Depends(require_csrf)])
def create_plan(
    body: PlanIn,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    if not db.get(VideoSource, body.video_id):
        raise BadRequest("视频源不存在", code="NO_VIDEO")
    if any(c not in "01" for c in body.days):
        raise BadRequest("days 只能是 7 位 0/1", code="BAD_DAYS")
    p = RecordPlan(**body.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    audit(db=db, action="record_plan.create", target=p.name, user=me, detail=body.model_dump())
    return _out(p)


@router.patch("/{plan_id}", dependencies=[Depends(require_csrf)])
def update_plan(
    plan_id: int, body: dict,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    p = db.get(RecordPlan, plan_id)
    if not p:
        raise NotFound("计划不存在")
    for k in ("name", "days", "start_time", "end_time", "enabled", "note"):
        if k in body and body[k] is not None:
            setattr(p, k, body[k])
    db.commit()
    db.refresh(p)
    audit(db=db, action="record_plan.update", target=p.name, user=me, detail=body)
    return _out(p)


@router.delete("/{plan_id}", dependencies=[Depends(require_csrf)])
def delete_plan(
    plan_id: int, db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "operator")),
) -> dict:
    p = db.get(RecordPlan, plan_id)
    if not p:
        raise NotFound("计划不存在")
    if p.video_id in _started_by_plan:
        registry.stop(p.video_id)
        _started_by_plan.discard(p.video_id)
    db.delete(p)
    db.commit()
    audit(db=db, action="record_plan.delete", target=p.name, user=me)
    return {"ok": True}


class PlanScheduler:
    """每 30 秒对齐一次计划。"""

    def __init__(self, session_factory, interval_s: int = 30) -> None:
        self._session_factory = session_factory
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception("录制计划调度失败")

    def tick(self, now: datetime | None = None) -> dict:
        now = now or datetime.now()
        want: dict[int, str] = {}
        with self._session_factory() as db:  # type: ignore[misc]
            for p in db.query(RecordPlan).filter(RecordPlan.enabled.is_(True)).all():
                if p.in_window(now):
                    want.setdefault(p.video_id, p.name)

            started, stopped = [], []
            for vid, name in want.items():
                if vid in _started_by_plan:
                    continue
                v = db.get(VideoSource, vid)
                if not v:
                    continue
                registry.start(vid, v.name, v.url)
                _started_by_plan.add(vid)
                started.append(name)

            for vid in list(_started_by_plan):
                if vid not in want:
                    registry.stop(vid)
                    _started_by_plan.discard(vid)
                    stopped.append(str(vid))

        if started or stopped:
            log.info("录制计划：开始 %s，停止 %s", started, stopped)
        return {"started": started, "stopped": stopped}


scheduler = PlanScheduler(session_factory=None)  # type: ignore[arg-type]
