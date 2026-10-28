"""巡航执行器：平台逐点下发 + 等到达 + 做动作。

为什么巡航要放在平台：X30 的导航接口（1003）一次只接**一个**目标点，
机器人没有"路线巡航"这种原子能力。旧系统也是这样做的——服务端循环：
下发下一个点 → 每 3s 查 1007 状态 → Status=0 到点 → 做动作 → 下一个。

这样才自洽：
- 进度、失败原因、到点时间都在平台库里（task_run_step），不依赖机器人内部状态；
- 暂停/取消 = 不再下发下一个点 + 发 1004 取消当前目标；
- 断网/超时 = 平台看得见（看门狗 + step 失败原因）。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime

from app.models.map_library import PointDraft
from app.models.task_run import TaskRun
from app.services.async_bridge import run_async
from app.models.task_run import TaskRunStep

log = logging.getLogger(__name__)

POLL_S = 3.0            # 查一次导航状态
ARRIVE_TIMEOUT_S = 240  # 单点最长等待（和旧系统一致：80 次 × 3s）


class CruiseRunner:
    """一条 task_run = 一个后台线程。并发数受平台设备数限制，通常 1-2 个。"""

    def __init__(self, session_factory) -> None:
        self._sf = session_factory
        self._threads: dict[int, threading.Thread] = {}
        self._cancel: dict[int, threading.Event] = {}
        self._pause: dict[int, threading.Event] = {}

    def running(self) -> list[int]:
        return [rid for rid, t in self._threads.items() if t.is_alive()]

    def start(self, run_id: int, adapter, from_seq: int = 0) -> bool:
        if run_id in self._threads and self._threads[run_id].is_alive():
            return False
        ev = threading.Event()
        self._cancel[run_id] = ev
        self._pause[run_id] = threading.Event()
        t = threading.Thread(target=self._run, args=(run_id, adapter, ev, from_seq),
                             daemon=True, name=f"cruise-{run_id}")
        self._threads[run_id] = t
        t.start()
        return True

    def pause(self, run_id: int) -> bool:
        ev = self._pause.get(run_id)
        if ev is None:
            return False
        ev.set()
        return True

    def resume(self, run_id: int) -> bool:
        ev = self._pause.get(run_id)
        if ev is None:
            return False
        ev.clear()
        return True

    def _wait_if_paused(self, run_id: int, stop: threading.Event) -> None:
        ev = self._pause.get(run_id)
        while ev is not None and ev.is_set() and not stop.is_set():
            stop.wait(0.5)

    def cancel(self, run_id: int, adapter) -> bool:
        ev = self._cancel.get(run_id)
        if ev is None:
            return False
        ev.set()
        try:
            if hasattr(adapter, "cancel"):
                res = adapter.cancel()
                if hasattr(res, "__await__"):
                    import asyncio
                    run_async(res)
        except Exception:  # noqa: BLE001
            log.exception("取消巡航时通知机器人失败")
        return True

    # ---- 执行 ----
    def _run(self, run_id: int, adapter, stop: threading.Event, from_seq: int = 0) -> None:
        with self._sf() as db:
            run = db.get(TaskRun, run_id)
            if run is None:
                return
            q = db.query(TaskRunStep).filter(TaskRunStep.run_id == run_id)
            if from_seq:
                q = q.filter(TaskRunStep.seq >= from_seq)
            steps = q.order_by(TaskRunStep.seq).all()
            points = {p.id: p for p in db.query(PointDraft).all()}
            run.status = "running"
            run.started_at = run.started_at or datetime.now()
            run.last_progress_at = datetime.now()
            db.commit()

        failed = 0
        for step in steps:
            if stop.is_set():
                break
            self._wait_if_paused(run_id, stop)
            point = points.get(step.point_id or -1)
            if point is None:
                self._mark(step.id, "failed", error="点位没有坐标（未在地图上打点）")
                failed += 1
                continue

            try:
                self._goto(adapter, point.x, point.y, point.theta or 0.0)
            except Exception as exc:  # noqa: BLE001
                self._mark(step.id, "failed", error=f"下发失败：{exc.__class__.__name__}: {exc}")
                failed += 1
                continue

            radius = float(getattr(point, "arrive_radius_m", 1.0) or 1.0)
            result, reason = self._wait_arrival(adapter, stop,
                                                target=(point.x, point.y),
                                                radius=radius)
            if stop.is_set():
                self._mark(step.id, "skipped", error="人工取消")
                break
            self._wait_if_paused(run_id, stop)
            if result == "suspect":
                # 不重试、不算失败：标 suspect + 告警，交人工决定
                self._mark(step.id, "suspect", error=reason,
                           result={"point": point.name, "x": point.x, "y": point.y})
                try:
                    from app.services.alarms import get_store

                    store = get_store()
                    if store is not None:
                        store.raise_external(
                            metric="loc_suspect", level="warn",
                            message=f"[{point.name}] {reason}", robot_id=run.robot_id)
                except Exception:  # noqa: BLE001
                    log.warning("suspect 告警发送失败", exc_info=True)
                continue
            if result != "arrived":
                self._mark(step.id, "failed", error=reason)
                failed += 1
                continue

            # 到点后执行这个点位配的动作（拍照/测温/停留），不是只记坐标
            # 期间占用"该点位"这把锁，避免另一台车同时挤进窄道口
            from app.services.resource_lock import release, try_acquire

            lock_key = f"point:{step.point_id}"
            got = try_acquire([lock_key], run_id=run_id, robot_id=run.robot_id or 0,
                              ttl_s=600)
            if not got:
                # 抢不到点位锁 = 另一台车正在这个点；不执行动作，避免两车挤窄道
                self._mark(step.id, "failed",
                           error="该点位被其他任务占用（资源锁），本点跳过")
                failed += 1
                continue
            try:
                action_result, action_err = self._do_action(adapter, step, run.robot_id)
            finally:
                release([lock_key], run_id=run_id)
            if action_err:
                self._mark(step.id, "failed",
                           error=f"到点但动作失败：{action_err}",
                           result={"point": point.name, "x": point.x, "y": point.y,
                                   "action": step.action})
                failed += 1
                continue
            self._mark(step.id, "ok",
                       result={"point": point.name, "x": point.x, "y": point.y,
                               "action": step.action, **(action_result or {})})
            with self._sf() as db:
                r = db.get(TaskRun, run_id)
                if r:
                    r.last_progress_at = datetime.now()
                    db.commit()

        with self._sf() as db:
            run = db.get(TaskRun, run_id)
            if run is None:
                return
            if stop.is_set():
                run.status = "cancelled"
            else:
                run.status = "done" if failed == 0 else "failed"
            if failed:
                run.dispatch_error = f"{failed} 个点位失败，详见各点结果"
            run.finished_at = datetime.now()
            db.commit()
        self._cancel.pop(run_id, None)
        self._pause.pop(run_id, None)

    def _goto(self, adapter, x: float, y: float, yaw: float) -> None:
        if getattr(adapter, "goto", None):
            res = adapter.goto(x, y, yaw)
        else:
            # 回退到 dispatch 时必须带 actionType，否则 JCROB 会按默认 photo 处理
            res = adapter.dispatch({"actions": [{
                "actionType": "nav",
                "actionParameters": [
                    {"key": "x", "value": x},
                    {"key": "y", "value": y},
                    {"key": "yaw", "value": yaw},
                ],
            }]})
        if hasattr(res, "__await__"):
            import asyncio
            run_async(res)

    def _ensure_sensor(self, robot_id: int | None, kind: str, label: str) -> int | None:
        """按（设备, 类型）找传感器，没有就建（测温/环境流共用）。"""
        from app.models.sensor import Sensor

        with self._sf() as db:
            q = db.query(Sensor).filter(Sensor.kind == kind)
            if robot_id is not None:
                q = q.filter(Sensor.robot_id == robot_id)
            row = q.first()
            if row is not None:
                return row.id
            row = Sensor(name=label, kind=kind, unit="℃", robot_id=robot_id, enabled=True)
            db.add(row)
            db.commit()
            db.refresh(row)
            return row.id

    def _camera_stream(self, robot_id: int | None) -> str | None:
        """从外设表里挑这台车的相机流（优先 camera，其次 thermal）。"""
        try:
            import json

            from app.models.peripheral import Peripheral
            from app.models.video_source import VideoSource

            with self._sf() as db:
                q = db.query(Peripheral).filter(Peripheral.enabled.is_(True),
                                                Peripheral.video_id.isnot(None))
                if robot_id is not None:
                    q = q.filter(Peripheral.robot_id == robot_id)
                rows = q.all()
                rows.sort(key=lambda p: 0 if p.kind == "camera" else 1)
                for p in rows:
                    v = db.get(VideoSource, p.video_id)
                    if v is not None and v.stream_name:
                        return v.stream_name
        except Exception:  # noqa: BLE001
            return None
        return None

    def _do_action(self, adapter, step, robot_id: int | None = None) -> tuple[dict | None, str | None]:
        """到点动作：能做的做，做不了的明确报"需要什么"，不假装成功。"""
        action = (step.action or "photo").lower()

        # 测温：SDK p47 onvif_camera/temperature —— 存一条读数，超温自动告警
        if action in ("thermal_temp", "thermometry", "measure"):
            getter = getattr(adapter, "get_camera_temperature", None)
            if getter is None:
                return None, "这台设备没有测温接口（需要红外热像仪 + 海康 ISAPI）"
            import asyncio

            res = getter()
            if hasattr(res, "__await__"):
                res = run_async(res)
            tmax = (res or {}).get("max")
            if tmax is None:
                return {"thermal": res}, "测温接口没有返回温度值"
            sid = self._ensure_sensor(robot_id, "ir_temp", "热像仪测温")
            if sid:
                from app.services.sensor_io import ingest_value

                with self._sf() as db:
                    ingest_value(db, sensor_id=sid, value=float(tmax), source="cruise_thermal")
            return {"thermal": res}, None

        fn = getattr(adapter, "capture", None)
        if action in ("photo", "video", "thermal"):
            if fn is None:
                return None, f"适配器还没有取图接口（{action} 需要真机确认抓拍 API）"
            stream = self._camera_stream(robot_id)
            res = fn(step, stream)
            if hasattr(res, "__await__"):
                import asyncio
                res = run_async(res)
            return {"capture": res}, None
        if action == "wait":
            time.sleep(3)
            return {"waited": 3}, None
        return {"skipped": action}, None

    def _wait_arrival(self, adapter, stop: threading.Event,
                      target: tuple[float, float] | None = None,
                      radius: float = 1.0) -> tuple[str, str]:
        """返回 (结果, 原因)，结果是 arrived / suspect / failed。

        suspect = 车端报完成但离目标超出容差（多半是定位漂移）：
        不重试、不判失败，交给人工重定位后重跑该点（避免把"该重定位"当成"任务失败"）。
        """
        deadline = time.time() + ARRIVE_TIMEOUT_S
        while time.time() < deadline:
            if stop.is_set():
                return "failed", "人工取消"
            try:
                order = adapter.get_order()
                if hasattr(order, "__await__"):
                    import asyncio
                    order = run_async(order)
            except Exception as exc:  # noqa: BLE001
                # 查询失败多半是机器人失联/网络断：这是"待人工确认位置"，不是普通超时
                return "failed", f"机器人失联（查询失败：{exc.__class__.__name__}），需人工确认位置"
            state = (order or {}).get("state")
            if state == "FINISHED":
                # 有目标坐标就再核对一次位姿：误差 > 1.5m 不算到点（防止空任务被当完成）
                if target is not None and hasattr(adapter, "get_pose"):
                    try:
                        pose = adapter.get_pose()
                        if hasattr(pose, "__await__"):
                            import asyncio
                            pose = run_async(pose)
                        if isinstance(pose, dict) and pose.get("x") is not None:
                            dx = float(pose["x"]) - float(target[0])
                            dy = float(pose["y"]) - float(target[1])
                            dist = (dx * dx + dy * dy) ** 0.5
                            if dist > radius * 2.5:
                                return "failed", (f"机器人报完成但离目标 {dist:.1f}m"
                                                  f"（{radius:.1f}m 的 2.5 倍以上，按失败处理）")
                            if dist > radius:
                                return "suspect", (f"机器人报完成但离目标 {dist:.1f}m"
                                                   f"（容差 {radius:.1f}m，疑似定位漂移，建议重置定位后重跑该点）")
                    except Exception:  # noqa: BLE001
                        pass
                return "arrived", ""
            if state == "FAILED":
                return "failed", "机器人报告无法到达"
            time.sleep(POLL_S)
        return "failed", f"超过 {ARRIVE_TIMEOUT_S}s 未到达"

    def _mark(self, step_id: int, status: str, *, error: str | None = None,
              result: dict | None = None) -> None:
        with self._sf() as db:
            step = db.get(TaskRunStep, step_id)
            if step is None:
                return
            step.status = status
            step.finished_at = datetime.now()
            step.error = (error or "")[:200] or None
            if result is not None:
                step.result_json = json.dumps(result, ensure_ascii=False)
            db.commit()


runner: CruiseRunner | None = None
