"""下发幂等 + 对账的测试（A 项）。"""

from __future__ import annotations

import pytest

from app.core.errors import PlatformError
from app.db.session import Base, SessionLocal, engine
from app.models.task_run import TaskRun, TaskRunStep  # noqa: F401
from app.services.task_dispatch import _claim_dispatch, reconcile_dispatches
from app.services import task_dispatch as td


def _ensure() -> None:
    Base.metadata.create_all(bind=engine)


def _mk(db, robot_id: int = 2) -> TaskRun:
    run = TaskRun(name="idem-test", robot_id=robot_id, status="planned",
                  dispatch_state="pending", dispatch_attempt=0)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def test_claim_sets_order_id_and_lease():
    _ensure()
    with SessionLocal() as db:
        run = _mk(db)
        try:
            oid = _claim_dispatch(db, run)
            db.refresh(run)
            assert oid == f"JC-R{run.id:06d}-A01"
            assert run.dispatch_state == "sending"
            assert run.dispatch_attempt == 1
            assert run.dispatch_lease_until is not None
        finally:
            db.delete(db.merge(run))
            db.commit()


def test_second_claim_is_rejected():
    _ensure()
    with SessionLocal() as db:
        run = _mk(db, robot_id=3)
        try:
            _claim_dispatch(db, run)
            with pytest.raises(PlatformError) as exc:
                _claim_dispatch(db, run)
            assert exc.value.code == "ORDER_IN_FLIGHT"
        finally:
            db.delete(db.merge(run))
            db.commit()


def test_reconcile_marks_failed_without_external_id():
    _ensure()
    from datetime import datetime, timedelta

    with SessionLocal() as db:
        run = _mk(db, robot_id=4)
        run.dispatch_state = "sending"
        run.dispatch_lease_until = datetime.now() - timedelta(seconds=1)
        db.commit()
        try:
            n = reconcile_dispatches(db)
            assert n >= 1
            db.refresh(run)
            assert run.dispatch_state == "failed"
            assert "对账" in (run.dispatch_error or "")
        finally:
            db.delete(db.merge(run))
            db.commit()


def test_reconcile_keeps_sent_when_external_id_present():
    _ensure()
    from datetime import datetime, timedelta

    with SessionLocal() as db:
        run = _mk(db, robot_id=5)
        run.dispatch_state = "sending"
        run.external_id = "robot-42"
        run.dispatch_lease_until = datetime.now() - timedelta(seconds=1)
        db.commit()
        try:
            reconcile_dispatches(db)
            db.refresh(run)
            assert run.dispatch_state == "sent"
        finally:
            db.delete(db.merge(run))
            db.commit()
