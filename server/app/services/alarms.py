"""告警推导 + 持久化。

两条线：
- `AlarmStore.evaluate()` 只在内存里判断"这一轮要不要报"，负责去重；
- 真正落地的是 `AlarmRecord` 表 —— 重启不丢、能按时间/级别/指标查。
  绑定了 session_factory 就走数据库，没绑定就退回内存（单测用）。

camera_id 的取舍：告警产生时如果能确定"这是哪一路摄像头看到的"，就固化下来；
确定不了就留 null。查询时 null 表示"没有关联视频"，前端不给回放入口，
而不是猜一个摄像头——那是给运维挖坑。
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


@dataclass
class Alarm:
    id: int
    metric: str
    level: str
    message: str
    value: Any = None
    started_at: str = field(default_factory=lambda: _now().isoformat(timespec="seconds"))
    acked_at: str | None = None
    acked_by: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "metric": self.metric, "level": self.level,
            "message": self.message, "value": self.value,
            "started_at": self.started_at, "acked_at": self.acked_at,
            "acked_by": self.acked_by, "camera_id": getattr(self, "camera_id", None),
        }


# ISA-18.2 式分级的简化落地：后果 × 允许响应时间
# P1 立即（安全/人身）、P2 紧急（设备/生产）、P3 一般、P4 提示
SAFETY_METRICS = ("estop", "env_gas", "smoke", "fire")


def priority_for(metric: str, level: str) -> str:
    m = (metric or "").lower()
    if level == "critical":
        if any(k in m for k in SAFETY_METRICS):
            return "P1"
        return "P2"
    if level == "warn":
        return "P3"
    return "P4"


class AlarmStore:
    def __init__(self, *, max_items: int = 200, dedupe_s: float = 60.0,
                 low_battery_warn: int = 20, low_battery_critical: int = 10,
                 offline_after_s: float = 10.0) -> None:
        self.max_items = max_items
        self.dedupe_s = dedupe_s
        self.low_battery_warn = low_battery_warn
        self.low_battery_critical = low_battery_critical
        self.offline_after_s = offline_after_s
        self._items: list[Alarm] = []
        self._last_raised: dict[str, float] = {}
        self._first_seen: dict[str, float] = {}
        # 置信度：同指标在窗口内反复超限，说明不是抖动，要升级
        self._recent_hits: dict[str, list[float]] = {}
        self.escalate_window_s = 300.0
        self.escalate_hits = 3
        self._lock = threading.Lock()
        self._session_factory: Callable[[], Session] | None = None

    # ---- 绑定数据库（main.py 启动时调用）----
    def attach_db(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    # ---- 求值 -----------------------------------------------------------
    def _cfg(self) -> dict:
        """阈值从平台设置读，改完立即生效（不重启）。"""
        try:
            from app.api.v1.settings import load_all
            s = load_all()
        except Exception:  # noqa: BLE001 - 设置读不到就用默认值
            s = {}
        return {
            "warn": int(s.get("alarm.battery_warn", self.low_battery_warn)),
            "critical": int(s.get("alarm.battery_critical", self.low_battery_critical)),
            "offline": float(s.get("alarm.offline_after_s", self.offline_after_s)),
            "dedupe": float(s.get("alarm.dedupe_s", self.dedupe_s)),
            "sustain": float(s.get("alarm.sustain_s", 0)),
        }

    def evaluate(self, *, status: dict, info: dict, age_s: float,
                 now: float | None = None,
                 camera_id: int | None = None, robot_id: int | None = None,
                 offline_after_s: float | None = None) -> list[Alarm]:
        now = time.monotonic() if now is None else now
        cfg = self._cfg()
        warn_at, crit_at = cfg["warn"], cfg["critical"]
        found: list[tuple[str, str, str, Any]] = []

        battery = info.get("battery")
        if isinstance(battery, (int, float)):
            if battery < crit_at:
                found.append(("battery", "critical", f"电量仅 {battery}%，需要立即回充", battery))
            elif battery < warn_at:
                found.append(("battery", "warn", f"电量 {battery}%，低于提醒阈值", battery))

        if info.get("driver_port") is True:
            found.append(("estop", "critical", "硬件急停被按下", True))

        offline_limit = float(offline_after_s or cfg["offline"])
        if age_s < 0 or age_s > offline_limit:
            # 抖动只报提醒，持续断线才升级成严重（默认 3 倍判定时间）
            lvl = "critical" if age_s > offline_limit * 3 else "warn"
            msg = f"机器人通信中断（{age_s:.0f}s 未更新）" if age_s >= 0 else "机器人通信中断"
            found.append(("offline", lvl, msg, round(age_s, 1)))

        # 置信度升级：同一指标 5 分钟内第 3 次出现，就按严重处理，
        # 避免"网络抖动 → 一直提示 → 值班忽略 → 真事故漏掉"
        with self._lock:
            for metric, level, message, value in list(found):
                rkey = f"{robot_id}:{metric}" if robot_id is not None else metric
                hits = self._recent_hits.setdefault(rkey, [])
                hits.append(now)
                hits[:] = [t for t in hits if now - t <= self.escalate_window_s]
                if level == "warn" and len(hits) >= self.escalate_hits:
                    idx = found.index((metric, level, message, value))
                    found[idx] = (metric, "critical",
                                  f"{message}（{int(self.escalate_window_s // 60)} 分钟内第 {len(hits)} 次）",
                                  value)

        new: list[Alarm] = []
        with self._lock:
            # 本轮没出现的条件，把"首次出现时间"清掉，下次重新计时
            prefix = f"{robot_id}:" if robot_id is not None else ""
            active = {f"{prefix}{m}" for m, _, _, _ in found}
            for k in list(self._first_seen):
                if k.startswith(prefix) and k not in active:
                    self._first_seen.pop(k, None)

            for metric, level, message, value in found:
                dkey = f"{robot_id}:{metric}" if robot_id is not None else metric
                first = self._first_seen.setdefault(dkey, now)
                if cfg["sustain"] > 0 and now - first < cfg["sustain"]:
                    continue  # 还没持续够久，先不报（防抖）
                last = self._last_raised.get(dkey)
                if last is not None and now - last < cfg["dedupe"]:
                    continue
                # 同一指标已有未解除的告警 → 更新它（计数/最近时间），不新增。
                # 否则一台设备离线 10 小时就是 600 条告警、600 张工单。
                if self._session_factory is not None and self._touch_open(robot_id, metric, message, value):
                    self._last_raised[dkey] = now
                    continue
                self._last_raised[dkey] = now
                alarm = Alarm(id=0, metric=metric, level=level, message=message, value=value)
                alarm.camera_id = camera_id  # type: ignore[attr-defined]
                if self._session_factory is not None:
                    self._persist(alarm, robot_id)
                else:
                    alarm.id = len(self._items) + 1
                self._items.append(alarm)
                new.append(alarm)
            if len(self._items) > self.max_items:
                self._items = self._items[-self.max_items:]
            # 本轮没出现的指标 → 自动恢复
            try:
                self._resolve_gone(robot_id, {f"{robot_id}:{m}" if robot_id is not None else m
                                              for m, _, _, _ in found})
            except Exception:  # noqa: BLE001
                pass
        return new

    def _touch_open(self, robot_id: int | None, metric: str, message: str, value) -> bool:
        """已有未解除的同指标告警就更新它并返回 True；没有返回 False。

        为什么需要：一台设备离线 10 小时，按分钟去重就是 600 条告警、600 张工单。
        行业做法是一条告警持续存在，直到条件消失或人工关闭。
        """
        try:
            from app.models.alarm import AlarmRecord

            with self._session_factory() as db:  # type: ignore[misc]
                # 表里没有 status 列：用 resolved_at 判断是否已恢复
                q = db.query(AlarmRecord).filter(
                    AlarmRecord.metric == metric,
                    AlarmRecord.resolved_at.is_(None),
                )
                if robot_id is not None:
                    q = q.filter(AlarmRecord.robot_id == robot_id)
                else:
                    q = q.filter(AlarmRecord.robot_id.is_(None))  # 没指定设备就别跨设备匹配
                row = q.order_by(AlarmRecord.id.desc()).first()
                if row is None:
                    return False
                row.message = message[:255]
                row.level = "critical" if "critical" in message or "第" in message else row.level
                row.value_json = json.dumps(
                    {"value": value, "at": datetime.now().isoformat(timespec="seconds")},
                    ensure_ascii=False)
                db.commit()
                return True
        except Exception:  # noqa: BLE001
            return False

    def _resolve_gone(self, robot_id: int | None, active: set[str]) -> None:
        """条件消失的告警自动恢复（active → resolved）。

        行业通行做法：告警要能自己好，不能全靠人点"关闭"——
        否则一次抖动会留下几十条永远挂着的"未确认"。
        """
        if self._session_factory is None:
            return
        from app.models.alarm import AlarmRecord

        prefix = f"{robot_id}:" if robot_id is not None else ""
        base = {k[len(prefix):] for k in active if k.startswith(prefix)} if prefix else active
        with self._session_factory() as db:  # type: ignore[misc]
            rows = (db.query(AlarmRecord)
                    .filter(AlarmRecord.resolved_at.is_(None),
                            AlarmRecord.closed_at.is_(None))
                    .all())
            changed = False
            for r in rows:
                if robot_id is not None and r.robot_id != robot_id:
                    continue
                if r.metric in base:
                    continue
                r.resolved_at = _now()
                changed = True
            if changed:
                db.commit()

    def _persist(self, alarm: Alarm, robot_id: int | None) -> None:
        from app.models.alarm import AlarmRecord

        with self._session_factory() as db:  # type: ignore[misc]
            rec = AlarmRecord(
                metric=alarm.metric, level=alarm.level, message=alarm.message,
                value_json=json.dumps(alarm.value, ensure_ascii=False) if alarm.value is not None else None,
                started_at=_now(), robot_id=robot_id,
                camera_id=getattr(alarm, "camera_id", None),
                priority=priority_for(alarm.metric, alarm.level),
            )
            db.add(rec)
            db.commit()
            db.refresh(rec)
            alarm.id = rec.id
            alarm.started_at = rec.started_at.isoformat(timespec="seconds")

            # 严重告警自动进工单（PPT 模块五：异常自动进工单）
            if alarm.level == "critical":
                try:
                    from app.services.work_orders import ensure_from_alarm
                    ensure_from_alarm(db, alarm)
                except Exception:  # noqa: BLE001 - 建单失败不能影响告警
                    pass
            # 落库后立即入队外发（非阻塞）
            try:
                from app.services import notify as notify_svc
                notify_svc.on_alarm(alarm.to_dict())
            except Exception:  # noqa: BLE001 - 外发失败不能影响告警主流程
                pass

    def _is_shelved(self, metric: str) -> bool:
        """同指标有未到期搁置 → 不上报告警（ISA-18.2 shelve）。"""
        try:
            from app.models.alarm import AlarmRecord

            if self._session_factory is None:
                return False
            with self._session_factory() as db:  # type: ignore[misc]
                row = (db.query(AlarmRecord)
                       .filter(AlarmRecord.metric == metric,
                               AlarmRecord.shelved_until.isnot(None))
                       .order_by(AlarmRecord.id.desc()).first())
                if row is None or row.shelved_until is None:
                    return False
                return row.shelved_until > datetime.now()
        except Exception:  # noqa: BLE001
            return False

    def raise_external(self, *, metric: str, level: str, message: str,
                       value: Any = None, camera_id: int | None = None,
                       robot_id: int | None = None) -> Alarm | None:
        """平台侧非遥测来源的告警（如环境传感器超限）。同样去重、同样落库。"""
        if self._is_shelved(metric):
            return None
        now = time.monotonic()
        with self._lock:
            last = self._last_raised.get(metric)
            if last is not None and now - last < self.dedupe_s:
                return None
            self._last_raised[metric] = now
            alarm = Alarm(id=0, metric=metric, level=level, message=message, value=value)
            alarm.camera_id = camera_id  # type: ignore[attr-defined]
            if self._session_factory is not None:
                self._persist(alarm, robot_id)
                if alarm.level == "critical":
                    try:
                        from app.services.work_orders import ensure_from_alarm
                        with self._session_factory() as _db:
                            ensure_from_alarm(_db, alarm)
                    except Exception:  # noqa: BLE001
                        pass
            else:
                alarm.id = len(self._items) + 1
            self._items.append(alarm)
            return alarm

    # ---- 查询与确认 -----------------------------------------------------
    def list(self, *, active_only: bool = False) -> list[dict]:
        if self._session_factory is not None:
            return self.query(limit=self.max_items, status="unacked" if active_only else None)["items"]
        with self._lock:
            items = [a for a in self._items if not (active_only and a.acked_at)]
            return [a.to_dict() for a in reversed(items)]

    def query(self, *, limit: int = 200, offset: int = 0, status: str | None = None,
              level: str | None = None, metric: str | None = None,
              date_from: str | None = None, date_to: str | None = None,
              q: str | None = None) -> dict:
        """数据库查询：告警中心/数据查询用它。"""
        from app.models.alarm import AlarmRecord

        if self._session_factory is None:
            items = self.list(active_only=(status == "unacked"))
            return {"total": len(items), "items": items[offset:offset + limit]}

        conds = []
        if status == "unacked" or status == "new":
            conds.append(AlarmRecord.acked_at.is_(None))
        elif status == "acked":
            conds.append(AlarmRecord.acked_at.is_not(None))
            conds.append(AlarmRecord.closed_at.is_(None))
        elif status == "handled":
            conds.append(AlarmRecord.handled_at.is_not(None))
            conds.append(AlarmRecord.closed_at.is_(None))
        elif status == "closed":
            conds.append(AlarmRecord.closed_at.is_not(None))
        elif status == "open":
            conds.append(AlarmRecord.closed_at.is_(None))
        if level:
            conds.append(AlarmRecord.level == level)
        if metric:
            conds.append(AlarmRecord.metric == metric)
        if date_from:
            conds.append(AlarmRecord.started_at >= datetime.fromisoformat(date_from))
        if date_to:
            conds.append(AlarmRecord.started_at < datetime.fromisoformat(date_to) + timedelta(days=1))
        if q:
            conds.append(AlarmRecord.message.like(f"%{q}%"))
        where = and_(*conds) if conds else None

        with self._session_factory() as db:  # type: ignore[misc]
            total = db.scalar(select(func.count()).select_from(AlarmRecord).where(where)) if where is not None \
                else db.scalar(select(func.count()).select_from(AlarmRecord))
            q = select(AlarmRecord).order_by(AlarmRecord.started_at.desc()).limit(limit).offset(offset)
            if where is not None:
                q = q.where(where)
            rows = db.scalars(q).all()
            items = [r.to_dict() for r in rows]
            # 双向关联：告警上带出已生成的工单 id，前端可直接跳过去
            try:
                from app.models.inspection import WorkOrder

                ids = [i["id"] for i in items]
                linked = {}
                if ids:
                    for wo in db.query(WorkOrder).filter(
                            WorkOrder.source == "alarm",
                            WorkOrder.source_id.in_(ids)).all():
                        linked.setdefault(wo.source_id, wo.id)
                for i in items:
                    i["work_order_id"] = linked.get(i["id"])
            except Exception:  # noqa: BLE001
                pass
            return {"total": total or 0, "items": items}

    def handle(self, alarm_id: int, who: str, note: str) -> dict | None:
        """处置：说明"为什么报警、做了什么"，不同于确认。"""
        if self._session_factory is not None:
            from app.models.alarm import AlarmRecord

            with self._session_factory() as db:  # type: ignore[misc]
                rec = db.get(AlarmRecord, alarm_id)
                if not rec:
                    return None
                rec.handled_at = _now()
                rec.handled_by = who
                rec.handle_note = note
                if rec.acked_at is None:      # 处置即视为已确认
                    rec.acked_at = rec.handled_at
                    rec.acked_by = who
                db.commit()
                db.refresh(rec)
                return rec.to_dict()
        return None

    def close(self, alarm_id: int, who: str, resolution: str, note: str) -> dict | None:
        if self._session_factory is not None:
            from app.models.alarm import AlarmRecord

            with self._session_factory() as db:  # type: ignore[misc]
                rec = db.get(AlarmRecord, alarm_id)
                if not rec:
                    return None
                rec.closed_at = _now()
                rec.closed_by = who
                rec.resolution = resolution
                rec.close_note = note
                if rec.acked_at is None:
                    rec.acked_at = rec.closed_at
                    rec.acked_by = who
                db.commit()
                db.refresh(rec)
                return rec.to_dict()
        return None

    def ack(self, alarm_id: int, who: str) -> dict | None:
        if self._session_factory is not None:
            from app.models.alarm import AlarmRecord

            with self._session_factory() as db:  # type: ignore[misc]
                rec = db.get(AlarmRecord, alarm_id)
                if not rec:
                    return None
                rec.acked_at = _now()
                rec.acked_by = who
                db.commit()
                db.refresh(rec)
                return rec.to_dict()
        with self._lock:
            for alarm in self._items:
                if alarm.id == alarm_id:
                    alarm.acked_at = _now().isoformat(timespec="seconds")
                    alarm.acked_by = who
                    return alarm.to_dict()
        return None


def get_store() -> "AlarmStore | None":
    """给 AI 结果等外部来源取当前 AlarmStore（未初始化返回 None）。"""
    return _STORE


_STORE = None


def bind_store(store: "AlarmStore") -> None:
    global _STORE
    _STORE = store
