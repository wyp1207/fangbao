"""任务执行事件时间线（TDD）。

对照 Open-RMF 的 task state 变化、Nav2 行为树节点事件、Temporal 的 activity
history：每次状态迁移都追加一条 (run_id, seq) 事件，出问题能按时间轴复盘，
而不是只知道 task_run.status 的最后一个值。
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.session import Base, SessionLocal, engine
from app.models.task_run import TaskEvent, TaskRun, TaskRunStep
from app.services import task_events


def _ensure() -> None:
    Base.metadata.create_all(bind=engine)


def _mk_run(db, robot_id: int, status: str = "planned", steps: int = 0) -> TaskRun:
    run = TaskRun(name="event-test", robot_id=robot_id, status=status,
                  dispatch_state="pending", dispatch_attempt=0)
    db.add(run)
    db.flush()
    for i in range(steps):
        db.add(TaskRunStep(run_id=run.id, seq=i + 1, action="photo", status="pending"))
    db.commit()
    db.refresh(run)
    return run


def _drop(db, *run_ids: int) -> None:
    """清掉本次测试造的数据：测试库是文件库，残留行会污染后续断言。"""
    for rid in run_ids:
        db.query(TaskEvent).filter(TaskEvent.run_id == rid).delete()
        db.query(TaskRunStep).filter(TaskRunStep.run_id == rid).delete()
        db.query(TaskRun).filter(TaskRun.id == rid).delete()
    db.commit()


class _FakeAdapter:
    """只回状态、不发网络：事件落点与适配器实现无关。"""

    def __init__(self) -> None:
        self.orders: list[dict] = []

    def dispatch(self, order):
        self.orders.append(order)
        return {"state": "RUNNING", "id": "EXT-EV-1"}

    def get_status(self):
        return {"status": "idle"}

    def get_info(self):
        return {"battery": 88}

    def get_order(self):
        return {"state": "FINISHED"}

    def pause(self):
        return {"ok": True}

    def resume(self):
        return {"ok": True}

    def cancel(self):
        return {"ok": True}


def _wire(monkeypatch) -> None:
    """绕开写开关和后台轮询线程，测的是"落事件"而不是适配器/线程。"""
    from app.services import task_dispatch as td

    monkeypatch.setattr(td, "_require_write", lambda: None)
    monkeypatch.setattr(td, "_poll_until_done", lambda *a, **k: None)


# ---------------- 模型 ----------------

def test_event_model_shape():
    assert TaskEvent.__tablename__ == "task_event"
    cols = {c.name for c in TaskEvent.__table__.columns}
    assert {"id", "run_id", "seq", "kind", "message",
            "data_json", "actor", "created_at"} <= cols


# ---------------- 服务 ----------------

def test_log_assigns_increasing_seq_per_run():
    _ensure()
    with SessionLocal() as db:
        a = _mk_run(db, 121)
        b = _mk_run(db, 122)
        rid_a, rid_b = a.id, b.id
        try:
            for kind in ("created", "dispatched", "done"):
                task_events.log(db, rid_a, kind, kind)
            task_events.log(db, rid_b, "created", "创建")
            db.commit()
            assert [e.seq for e in task_events.list_events(db, rid_a)] == [1, 2, 3]
            assert [e.seq for e in task_events.list_events(db, rid_b)] == [1]
        finally:
            _drop(db, rid_a, rid_b)


def test_log_persists_fields_and_json_data():
    _ensure()
    with SessionLocal() as db:
        run = _mk_run(db, 123)
        rid = run.id
        try:
            task_events.log(db, rid, "dispatched", "已下发到机器人",
                            data={"order_id": "JC-R000001-A01"}, actor="alice")
            db.commit()
            rows = task_events.list_events(db, rid)
            assert len(rows) == 1
            row = rows[0]
            assert row.kind == "dispatched"
            assert row.message == "已下发到机器人"
            assert row.actor == "alice"
            assert json.loads(row.data_json or "{}") == {"order_id": "JC-R000001-A01"}
            assert row.created_at is not None
        finally:
            _drop(db, rid)


def test_unique_run_seq_blocks_duplicate_row():
    """(run_id, seq) 唯一：并发撞号必须报 IntegrityError，不能静默写两条。"""
    _ensure()
    with SessionLocal() as db:
        run = _mk_run(db, 161)
        rid = run.id
        try:
            task_events.log(db, rid, "created", "第一条")
            db.commit()
            with pytest.raises(IntegrityError):
                db.add(TaskEvent(run_id=rid, seq=1, kind="created", message="撞号"))
                db.flush()
            db.rollback()
        finally:
            _drop(db, rid)


def test_log_retries_on_seq_conflict(monkeypatch):
    """撞号后重算 seq 再写：算出的 seq 已被占用时，第二次必须落到 max(seq)+1。"""
    _ensure()
    with SessionLocal() as db:
        run = _mk_run(db, 162)
        rid = run.id
        try:
            task_events.log(db, rid, "created", "占位")
            db.commit()

            real_next = task_events._next_seq
            calls = {"n": 0}

            def fake_next(db_, run_id):
                calls["n"] += 1
                return 1 if calls["n"] == 1 else real_next(db_, run_id)

            monkeypatch.setattr(task_events, "_next_seq", fake_next)
            ev = task_events.log(db, rid, "dispatched", "撞号重试")
            db.commit()
            assert ev.seq == 2
            assert calls["n"] >= 2, "撞号必须重算 seq，不能一次失败就放弃"
            assert [e.seq for e in task_events.list_events(db, rid)] == [1, 2]
        finally:
            _drop(db, rid)


def test_list_events_empty_for_unknown_run():
    _ensure()
    with SessionLocal() as db:
        assert task_events.list_events(db, 999999) == []


# ---------------- API ----------------

def test_events_api_404_for_unknown_run(auth_client):
    r = auth_client.get("/api/v1/task-runs/999999/events")
    assert r.status_code == 404


def test_create_run_logs_created_and_api_lists_it(auth_client):
    r = auth_client.post("/api/v1/task-runs", json={"name": "事件 API 测试"})
    assert r.status_code == 200, r.text
    run_id = r.json()["id"]
    try:
        r = auth_client.get(f"/api/v1/task-runs/{run_id}/events")
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert items, "创建 run 必须留下 created 事件"
        assert items[0]["kind"] == "created"
        assert items[0]["seq"] == 1
        assert items[0]["run_id"] == run_id
        assert items[0]["created_at"], "时间线要显示时间"
    finally:
        with SessionLocal() as db:
            _drop(db, run_id)


# ---------------- 下发链路关键迁移 ----------------

def test_dispatch_logs_dispatched_with_order_id(monkeypatch):
    _ensure()
    _wire(monkeypatch)
    from app.services import task_dispatch as td

    with SessionLocal() as db:
        run = _mk_run(db, 131, steps=1)
        rid = run.id
        try:
            run = td.dispatch(db, run, _FakeAdapter())
            assert run.status == "running"
            rows = task_events.list_events(db, rid)
            assert [e.kind for e in rows] == ["dispatched"]
            assert run.order_id and run.order_id in rows[0].message
            assert json.loads(rows[0].data_json or "{}")["order_id"] == run.order_id
        finally:
            _drop(db, rid)


def test_pause_resume_cancel_log_events(monkeypatch):
    _ensure()
    _wire(monkeypatch)
    from app.services import task_dispatch as td

    with SessionLocal() as db:
        run = _mk_run(db, 141, status="running", steps=1)
        rid = run.id
        try:
            td.pause(db, run, _FakeAdapter())
            td.resume(db, run, _FakeAdapter())
            td.cancel(db, run, _FakeAdapter(), reason="测试取消")
            assert [e.kind for e in task_events.list_events(db, rid)] == [
                "paused", "resumed", "cancelled"]
            db.refresh(run)
            assert run.status == "cancelled"
        finally:
            _drop(db, rid)


def test_retry_step_logs_step_retry(auth_client, monkeypatch):
    from app.api.v1 import task_runs as tr_api
    from app.services import task_dispatch as td

    class _CapAdapter:
        def capture(self, step):
            return {"photo": "retry.jpg"}

    monkeypatch.setattr(td, "_require_write", lambda: None)
    monkeypatch.setattr(tr_api, "_adapter_for", lambda db, run: _CapAdapter())

    r = auth_client.post("/api/v1/task-runs", json={"name": "重试事件测试"})
    assert r.status_code == 200, r.text
    run_id = r.json()["id"]
    with SessionLocal() as db:
        db.add(TaskRunStep(run_id=run_id, seq=1, action="photo", status="failed"))
        db.commit()
    try:
        r = auth_client.post(f"/api/v1/task-runs/{run_id}/steps/1/retry")
        assert r.status_code == 200, r.text
        with SessionLocal() as db:
            kinds = [e.kind for e in task_events.list_events(db, run_id)]
        assert "step_retry" in kinds
    finally:
        with SessionLocal() as db:
            _drop(db, run_id)


def test_event_failure_does_not_roll_back_dispatch(monkeypatch):
    """事件存储挂了，下发必须照旧成功：时间线是旁路，不是主链路的前提。"""
    _ensure()
    _wire(monkeypatch)
    from app.services import task_dispatch as td

    def boom(*a, **k):
        raise RuntimeError("event store down")

    monkeypatch.setattr(task_events, "log", boom)
    with SessionLocal() as db:
        run = _mk_run(db, 151, steps=1)
        rid = run.id
        try:
            run = td.dispatch(db, run, _FakeAdapter())
            assert run.status == "running"
            assert run.order_id
            assert run.dispatch_state == "sent"
            assert task_events.list_events(db, rid) == []
        finally:
            _drop(db, rid)
