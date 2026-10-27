"""任务互斥 + 人工接管的测试。"""

from __future__ import annotations

import pytest

from app.core.errors import PlatformError
from app.db.session import Base, SessionLocal, engine
from app.models.task_run import TaskRun  # noqa: F401  确保模型已注册
from app.services.task_lock import active_run, assert_free, takeover


def _ensure_tables() -> None:
    Base.metadata.create_all(bind=engine)


def _mk_run(db, robot_id: int, status: str = "running") -> TaskRun:
    run = TaskRun(name="lock-test-%s" % robot_id, robot_id=robot_id, status=status)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def test_second_dispatch_is_blocked():
    _ensure_tables()
    with SessionLocal() as db:
        first = _mk_run(db, 2)
        try:
            busy = active_run(db, 2)
            assert busy is not None and busy["id"] == first.id
            with pytest.raises(PlatformError) as exc:
                assert_free(db, 2, first.id + 999)
            assert exc.value.code == "RUN_BUSY"
            assert_free(db, 2, first.id)      # 自己那条不算冲突
        finally:
            db.query(TaskRun).filter(TaskRun.id == first.id).delete()
            db.commit()


def test_takeover_cancels_running_runs():
    _ensure_tables()
    with SessionLocal() as db:
        a = _mk_run(db, 3)
        b = _mk_run(db, 3)
        try:
            n = takeover(db, 3, reason="人工接管测试")
            assert n == 2
            db.expire_all()
            assert db.get(TaskRun, a.id).status == "cancelled"
            assert db.get(TaskRun, b.id).status == "cancelled"
            assert db.get(TaskRun, a.id).dispatch_error == "人工接管测试"
            assert active_run(db, 3) is None
        finally:
            db.query(TaskRun).filter(TaskRun.name == "lock-test-3").delete()
            db.commit()


def test_no_active_run_is_free():
    _ensure_tables()
    with SessionLocal() as db:
        assert active_run(db, 999999) is None
        assert_free(db, 999999, 1)   # 不抛异常
