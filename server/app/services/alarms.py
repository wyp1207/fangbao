"""告警推导（W2 最小版）。

只做“不用阈值也能判定”的四条：电量、硬件急停、通信中断、数据缺失。
环境类（lel/smoke/temperature）没有现场标定值，一律不求值——
页面显示“阈值未标定”，不拿占位值冒充。

存内存环形缓冲，不落库：
ponytail: 现在只需要“驾驶舱最近告警 + 确认”，不需要历史检索；
W5 做告警中心时再加表与迁移，届时把 evaluate 的产物写库即可。
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class Alarm:
    id: int
    metric: str
    level: str          # warn | critical
    message: str
    value: Any = None
    started_at: str = field(default_factory=_now_iso)
    acked_at: str | None = None
    acked_by: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


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
        self._seq = 0
        self._lock = threading.Lock()

    # ---- 求值 -----------------------------------------------------------
    def evaluate(self, *, status: dict, info: dict, age_s: float,
                 now: float | None = None) -> list[Alarm]:
        """按当前快照求值，返回本次新增的告警。"""
        now = time.monotonic() if now is None else now
        found: list[tuple[str, str, str, Any]] = []

        battery = info.get("battery")
        if isinstance(battery, (int, float)):
            if battery < self.low_battery_critical:
                found.append(("battery", "critical", f"电量仅 {battery}%，需要立即回充", battery))
            elif battery < self.low_battery_warn:
                found.append(("battery", "warn", f"电量 {battery}%，低于提醒阈值", battery))

        if info.get("driver_port") is True:
            found.append(("estop", "critical", "硬件急停被按下", True))

        if age_s < 0 or age_s > self.offline_after_s:
            found.append(("offline", "critical",
                          f"机器人通信中断（{age_s:.0f}s 未更新）" if age_s >= 0 else "机器人通信中断",
                          round(age_s, 1)))

        new: list[Alarm] = []
        with self._lock:
            for metric, level, message, value in found:
                last = self._last_raised.get(metric)
                if last is not None and now - last < self.dedupe_s:
                    continue  # 去重窗口内不重复产生
                self._last_raised[metric] = now
                self._seq += 1
                alarm = Alarm(id=self._seq, metric=metric, level=level,
                              message=message, value=value)
                self._items.append(alarm)
                new.append(alarm)
            if len(self._items) > self.max_items:
                self._items = self._items[-self.max_items:]
        return new

    # ---- 查询与确认 -----------------------------------------------------
    def list(self, *, active_only: bool = False) -> list[dict]:
        with self._lock:
            items = [a for a in self._items if not (active_only and a.acked_at)]
            return [a.to_dict() for a in reversed(items)]

    def ack(self, alarm_id: int, who: str) -> dict | None:
        with self._lock:
            for alarm in self._items:
                if alarm.id == alarm_id:
                    alarm.acked_at = _now_iso()
                    alarm.acked_by = who
                    return alarm.to_dict()
        return None
