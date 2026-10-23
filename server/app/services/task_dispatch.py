"""任务下发链路（写操作骨架）。

现在真机协议没确认，所以这一层做的是**与协议无关的部分**：
状态机、幂等、审计、超时看门狗、失败回退、权限与开关。
真机到了，只需要在适配器的 `dispatch/pause/resume/cancel` 里填 HTTP 调用。

状态照 VDA5050 对齐（INITIALIZING/RUNNING/PAUSED/FINISHED/FAILED），
换四足/挂轨时语义不用重讲。

开关：`robot.write_enabled` 默认关。关着的时候所有写接口返回 403 WRITE_LOCKED，
并明确告诉前端"缺什么"——不做假成功。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime

from app.core.errors import BadRequest, PlatformError
from app.models.task_run import TaskRun, TaskRunStep
from app.models.task_template import TaskTemplate

log = logging.getLogger(__name__)

# VDA5050 → 平台状态
STATE_MAP = {
    "INITIALIZING": "planned",
    "RUNNING": "running",
    "PAUSED": "running",
    "FINISHED": "done",
    "FAILED": "failed",
}


def _write_enabled() -> bool:
    from app.api.v1.settings import load_all

    try:
        return bool(load_all().get("robot.write_enabled", False))
    except Exception:  # noqa: BLE001
        return False


def _require_write() -> None:
    if not _write_enabled():
        raise PlatformError(
            "写操作未开启：需真机联调通过 + 现场授权书，然后在系统设置开启「允许下发任务」",
            code="WRITE_LOCKED", status_code=403,
        )


def _call(fn, *args):
    """适配器可能是 async 也可能是同步：统一在这里收口（同步端点跑在线程池，没事件循环）。"""
    import asyncio
    import inspect

    res = fn(*args)
    if inspect.isawaitable(res):
        return asyncio.run(res)
    return res


PREFLIGHT_MIN_BATTERY = 30.0


def preflight(db, run: TaskRun, adapter) -> dict:
    """下发前检查机器人状态。返回 {"ok": bool, "reason": str, "checks": {...}}。

    评审共识：宁可在平台侧拒绝，也不要在急停/手动/低电量时把目标点发下去。
    """
    checks: dict[str, str] = {}
    try:
        status = adapter.get_status()
        info = adapter.get_info()
        import asyncio, inspect
        if inspect.isawaitable(status):
            status = asyncio.run(status)
        if inspect.isawaitable(info):
            info = asyncio.run(info)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"读不到机器人状态：{exc.__class__.__name__}",
                "checks": {"link": "fail"}}

    st = (status or {}).get("status") if isinstance(status, dict) else {}
    st = st if isinstance(st, dict) else {}
    state_text = str(st.get("status") or status.get("status") if isinstance(status, dict) else "")
    checks["motion_state"] = state_text or "unknown"

    if "急停" in state_text or state_text.lower() in ("estop", "emergency_stop"):
        return {"ok": False, "reason": f"机器人处于急停状态（{state_text}），先解除急停", "checks": checks}
    if "手动" in state_text or state_text.lower() in ("manual",):
        return {"ok": False, "reason": "机器人处于手动模式，切回自动再下发", "checks": checks}

    battery = (info or {}).get("battery") if isinstance(info, dict) else None
    checks["battery"] = str(battery)
    if isinstance(battery, (int, float)) and battery < PREFLIGHT_MIN_BATTERY:
        return {"ok": False, "reason": f"电量 {battery:.0f}% 低于 {PREFLIGHT_MIN_BATTERY:.0f}%，先回充",
                "checks": checks}

    # 同一台机器人不允许两个任务同时跑
    running = (db.query(TaskRun)
               .filter(TaskRun.robot_id == run.robot_id,
                       TaskRun.id != run.id,
                       TaskRun.status == "running")
               .first())
    if running is not None:
        return {"ok": False, "reason": f"这台机器人正在执行任务 #{running.id}（{running.name}）",
                "checks": checks}

    checks["pending_runs"] = "ok"
    return {"ok": True, "reason": "", "checks": checks}


def _order_payload(db, template: TaskTemplate | None, steps: list[TaskRunStep]) -> dict:
    """下发给机器人的订单结构。坐标必须带上——只给 pointId 机器人不知道去哪。"""
    from app.models.map_library import PointDraft

    points = {p.id: p for p in db.query(PointDraft).all()}
    return {
        "orderId": f"JC-{int(time.time() * 1000)}",
        "orderUpdateId": 0,
        "actions": [
            {
                "actionId": f"a{s.seq}",
                "actionType": s.action or "photo",
                "actionParameters": [
                    {"key": "pointId", "value": str(s.point_id or "")},
                    {"key": "pointName", "value": s.point_name or ""},
                    {"key": "x", "value": getattr(points.get(s.point_id or -1), "x", 0.0)},
                    {"key": "y", "value": getattr(points.get(s.point_id or -1), "y", 0.0)},
                    {"key": "yaw", "value": getattr(points.get(s.point_id or -1), "theta", 0.0) or 0.0},
                ],
            }
            for s in steps
        ],
        "loop": bool(template.loop) if template else False,
        "note": "平台下发",
    }


def dispatch(db, run: TaskRun, adapter) -> TaskRun:
    """把一条 planned 的执行记录下发给机器人。"""
    _require_write()
    if run.status != "planned":
        raise BadRequest(f"当前状态 {run.status} 不能下发", code="BAD_STATUS")

    gate = preflight(db, run, adapter)
    if not gate["ok"]:
        raise PlatformError(gate["reason"], code="PREFLIGHT_FAILED", status_code=409)

    steps = db.query(TaskRunStep).filter(TaskRunStep.run_id == run.id).all()
    if not steps:
        raise BadRequest("这条计划没有点位，先补点位", code="EMPTY_STEPS")

    template = db.get(TaskTemplate, run.template_id) if run.template_id else None
    order = _order_payload(db, template, steps)

    from app.adapters.jcrob import errors as jerr

    try:
        res = _call(adapter.dispatch, order)
    except jerr.NotSupported as exc:
        raise PlatformError(f"机器人不支持下发：{exc.reason}", code="NOT_SUPPORTED",
                            status_code=501) from exc

    run.status = STATE_MAP.get(res.get("state", "RUNNING"), "running")
    run.external_id = str(res.get("id") or run.external_id or "")
    run.dispatched_at = datetime.now()
    run.dispatch_error = None
    run.last_progress_at = datetime.now()
    run.order_json = json.dumps(order, ensure_ascii=False)
    db.commit()
    db.refresh(run)
    log.info("任务下发 #%s → %s", run.id, run.external_id)

    # 下发 ≠ 完成：异步轮询订单状态，把 run 从 running 推到 done/failed。
    # 之前没有这一段，任务永远停在 running，30s 后看门狗误报"卡住"并建告警。
    import threading

    run_id = run.id
    threading.Thread(target=_poll_until_done, args=(run_id, adapter),
                     daemon=True, name=f"dispatch-{run_id}").start()
    return run


def _poll_until_done(run_id: int, adapter, timeout_s: int = 1800) -> None:
    """后台把单点下发跟到终态（最多 30 分钟）。"""
    import time

    from app.db.session import SessionLocal
    from app.models.task_run import TaskRun

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(3)
        try:
            order = _call(adapter.get_order)
        except Exception:  # noqa: BLE001
            continue
        state = (order or {}).get("state")
        if state in ("FINISHED", "FAILED"):
            with SessionLocal() as db:
                run = db.get(TaskRun, run_id)
                if run is None or run.status != "running":
                    return
                run.status = "done" if state == "FINISHED" else "failed"
                run.finished_at = datetime.now()
                if state == "FAILED":
                    run.dispatch_error = "机器人报告任务失败"
                steps = db.query(TaskRunStep).filter(TaskRunStep.run_id == run_id).all()
                for st in steps:
                    if st.status in ("pending", "running"):
                        st.status = "ok" if state == "FINISHED" else "failed"
                        st.finished_at = datetime.now()
                db.commit()
            return
    # 超时：明确标失败，不留在 running 里让人猜
    with SessionLocal() as db:
        run = db.get(TaskRun, run_id)
        if run is not None and run.status == "running":
            run.status = "failed"
            run.dispatch_error = f"超过 {timeout_s // 60} 分钟未收到完成状态"
            run.finished_at = datetime.now()
            db.commit()


def pause(db, run: TaskRun, adapter) -> TaskRun:
    _require_write()
    if run.status != "running":
        raise BadRequest("只有执行中的任务能暂停", code="BAD_STATUS")
    _call(adapter.pause)
    run.paused_at = datetime.now()
    db.commit()
    return run


def resume(db, run: TaskRun, adapter) -> TaskRun:
    _require_write()
    if not run.paused_at:
        raise BadRequest("任务不在暂停状态", code="NOT_PAUSED")
    _call(adapter.resume)
    run.paused_at = None
    run.last_progress_at = datetime.now()
    db.commit()
    return run


def cancel(db, run: TaskRun, adapter) -> TaskRun:
    _require_write()
    if run.status in ("done", "cancelled"):
        raise BadRequest("已结束的任务不能取消", code="BAD_STATUS")
    _call(adapter.cancel)
    run.status = "cancelled"
    run.finished_at = datetime.now()
    db.commit()
    return run


# ---------------- 看门狗 ----------------

WATCHDOG_STUCK_S = 30


def check_stuck(session_factory) -> int:
    """执行中超过 30s 没有进度更新 → 产生告警（不自动 cancel，避免误停真机）。"""
    from app.models.alarm import AlarmRecord

    now = datetime.now()
    n = 0
    with session_factory() as db:
        rows = (db.query(TaskRun)
                .filter(TaskRun.status == "running",
                        TaskRun.paused_at.is_(None))
                .all())
        for r in rows:
            last = r.last_progress_at or r.dispatched_at or r.started_at
            if last is None:
                continue
            if (now - last).total_seconds() < WATCHDOG_STUCK_S:
                continue
            exists = (db.query(AlarmRecord)
                      .filter(AlarmRecord.metric == f"task_stuck_{r.id}",
                              AlarmRecord.resolved_at.is_(None))
                      .first())
            if exists:
                continue
            from app.services import alarms as alarms_mod

            store = alarms_mod.get_store()
            if store is not None:
                store.raise_external(
                    metric=f"task_stuck_{r.id}", level="critical",
                    message=f"任务「{r.name}」下发后 {WATCHDOG_STUCK_S}s 无进度，可能没收到订单",
                )
                n += 1
    return n


class TaskWatchdog:
    def __init__(self, session_factory, interval_s: int = 15) -> None:
        self._sf = session_factory
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
        while not self._stop.is_set():
            try:
                n = check_stuck(self._sf)
                if n:
                    log.warning("任务看门狗：%s 条任务无进度", n)
            except Exception:  # noqa: BLE001
                log.exception("任务看门狗异常")
            if self._stop.wait(self.interval_s):
                break


watchdog: TaskWatchdog | None = None
