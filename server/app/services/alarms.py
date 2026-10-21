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
                 camera_id: int | None = None, robot_id: int | None = None) -> list[Alarm]:
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

        if age_s < 0 or age_s > cfg["offline"]:
            found.append(("offline", "critical",
                          f"机器人通信中断（{age_s:.0f}s 未更新）" if age_s >= 0 else "机器人通信中断",
                          round(age_s, 1)))

        # 置信度升级：同一指标 5 分钟内第 3 次出现，就按严重处理，
        # 避免"网络抖动 → 一直提示 → 值班忽略 → 真事故漏掉"
        with self._lock:
            for metric, level, message, value in list(found):
                hits = self._recent_hits.setdefault(metric, [])
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
            active = {m for m, _, _, _ in found}
            for k in list(self._first_seen):
                if k not in active:
                    self._first_seen.pop(k, None)

            for metric, level, message, value in found:
                first = self._first_seen.setdefault(metric, now)
                if cfg["sustain"] > 0 and now - first < cfg["sustain"]:
                    continue  # 还没持续够久，先不报（防抖）
                last = self._last_raised.get(metric)
                if last is not None and now - last < cfg["dedupe"]:
                    continue
                self._last_raised[metric] = now
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
        return new

    def _persist(self, alarm: Alarm, robot_id: int | None) -> None:
        from app.models.alarm import AlarmRecord

        with self._session_factory() as db:  # type: ignore[misc]
            rec = AlarmRecord(
                metric=alarm.metric, level=alarm.level, message=alarm.message,
                value_json=json.dumps(alarm.value, ensure_ascii=False) if alarm.value is not None else None,
                started_at=_now(), robot_id=robot_id,
                camera_id=getattr(alarm, "camera_id", None),
            )
            db.add(rec)
            db.commit()
            db.refresh(rec)
            alarm.id = rec.id
            alarm.started_at = rec.started_at.isoformat(timespec="seconds")
            # 落库后立即入队外发（非阻塞）
            try:
                from app.services import notify as notify_svc
                notify_svc.on_alarm(alarm.to_dict())
            except Exception:  # noqa: BLE001 - 外发失败不能影响告警主流程
                pass

    def raise_external(self, *, metric: str, level: str, message: str,
                       value: Any = None, camera_id: int | None = None,
                       robot_id: int | None = None) -> Alarm | None:
        """平台侧非遥测来源的告警（如环境传感器超限）。同样去重、同样落库。"""
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
            return {"total": total or 0, "items": [r.to_dict() for r in rows]}

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
