"""审计发现的回归测试：重启恢复 / 取消确认 / 暂停开关 / 模板下发 / 升级不吞。"""

from __future__ import annotations

import time

from app.core.config import get_settings
from app.db.session import Base, SessionLocal, engine
from app.models.task_run import TaskRun, TaskRunStep  # noqa: F401
from app.services import task_dispatch as td


def _ensure():
    Base.metadata.create_all(bind=engine)


def test_mark_stale_runs_marks_failed():
    """重启恢复：残留 running 必须被标 failed（此前 NameError 从未执行）。"""
    _ensure()
    with SessionLocal() as db:
        run = TaskRun(name="stale-test", robot_id=1, status="running")
        db.add(run)
        db.commit()
        rid = run.id
    n = td.mark_stale_runs(SessionLocal)
    assert n >= 1
    with SessionLocal() as db:
        row = db.get(TaskRun, rid)
        assert row.status == "failed"
        assert "服务重启" in (row.dispatch_error or "")
        db.delete(row)
        db.commit()


class _StuckAdapter:
    def cancel(self):
        return {"ok": True}

    def get_order(self):
        return {"state": "RUNNING"}


class _StoppedAdapter:
    def cancel(self):
        return {"ok": True}

    def get_order(self):
        return {"state": "FINISHED"}


def test_cancel_reports_failed_when_robot_still_running(monkeypatch):
    """发取消但车还在跑：不能写 cancelled，要写 failed + 提示。"""
    _ensure()
    monkeypatch.setattr(td, "_require_write", lambda: None)
    monkeypatch.setattr(td, "_confirm_stopped", lambda adapter, timeout_s=8.0: False)
    with SessionLocal() as db:
        run = TaskRun(name="cancel-stuck", robot_id=1, status="running")
        db.add(run)
        db.commit()
        out = td.cancel(db, run, _StuckAdapter(), reason="测试")
        assert out.status == "failed"
        assert "仍在执行" in (out.dispatch_error or "")
        db.delete(out)
        db.commit()


def test_cancel_ok_when_robot_stopped(monkeypatch):
    _ensure()
    monkeypatch.setattr(td, "_require_write", lambda: None)
    monkeypatch.setattr(td, "_confirm_stopped", lambda adapter, timeout_s=8.0: True)
    with SessionLocal() as db:
        run = TaskRun(name="cancel-ok", robot_id=1, status="running")
        db.add(run)
        db.commit()
        out = td.cancel(db, run, _StoppedAdapter(), reason="测试")
        assert out.status == "cancelled"
        db.delete(out)
        db.commit()


def test_cruise_pause_flag_controls_wait():
    """暂停开关：pause 后线程会在检查点等待，resume 后继续（只测开关本身）。"""
    from app.services import cruise as cruise_mod

    runner = cruise_mod.CruiseRunner(session_factory=lambda: None)
    runner._pause[1] = __import__("threading").Event()
    assert runner.pause(1) is True
    assert runner._pause[1].is_set()
    assert runner.resume(1) is True
    assert not runner._pause[1].is_set()
    runner._pause.pop(1)


def test_template_dispatch_creates_run(auth_client):
    """模板一键下发不再 501：关写开关时 403，开写开关时创建并下发。"""
    _ensure()
    auth_client.put("/api/v1/settings", json={"values": {"robot.write_enabled": False}})
    from app.models.map_library import PlatformMap, PointDraft

    with SessionLocal() as db:
        m = db.query(PlatformMap).first()
        if m is None:
            m = PlatformMap(name="test-map", floor="1F", station="tests", image_path="test.png")
            db.add(m)
            db.commit()
            db.refresh(m)
        p = db.query(PointDraft).filter(PointDraft.map_id == m.id).first()
        if p is None:
            p = PointDraft(map_id=m.id, name="P1", x=1.0, y=2.0, theta=0.0)
            db.add(p)
            db.commit()
            db.refresh(p)
        pid = p.id
    tpl = auth_client.post("/api/v1/task-templates", json={
        "name": "tpl-dispatch-test", "robot_id": 1,
        "actions": [{"point_id": pid, "action": "wait", "sec": 1}],
    })
    assert tpl.status_code in (200, 201), tpl.text
    tid = tpl.json()["id"]
    r = auth_client.post("/api/v1/task-templates/%s/dispatch" % tid)
    assert r.status_code == 403, r.text
    auth_client.put("/api/v1/settings", json={"values": {"robot.write_enabled": True}})
    try:
        r2 = auth_client.post("/api/v1/task-templates/%s/dispatch" % tid)
        assert r2.status_code == 200, r2.text
        assert r2.json().get("run_id")
    finally:
        auth_client.put("/api/v1/settings", json={"values": {"robot.write_enabled": False}})
