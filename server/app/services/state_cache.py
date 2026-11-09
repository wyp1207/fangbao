"""进程内状态缓存。

单进程是刻意选择：缓存、WS、后台循环都在一个事件循环里，不引 Redis。
新鲜度一律用服务端 recv_ts，不用机器人报文时间（设备 NTP 状态未知）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Snapshot:
    status: dict[str, Any] = field(default_factory=dict)
    info: dict[str, Any] = field(default_factory=dict)
    galileo: dict[str, Any] = field(default_factory=dict)
    pose: dict[str, Any] = field(default_factory=dict)
    recv_ts: float = 0.0
    last_error: str | None = None
    consecutive_failures: int = 0
    poll_count: int = 0

    @property
    def age_s(self) -> float:
        return round(time.monotonic() - self.recv_ts, 3) if self.recv_ts else -1.0


class StateCache:
    # 在线判定阈值：默认 5s；适配器（如 X30 30s）可覆盖，避免 UI 与告警两套口径
    offline_after_s: float = 5.0

    def __init__(self) -> None:
        self._snapshot = Snapshot()

    @property
    def snapshot(self) -> Snapshot:
        return self._snapshot

    def update(self, *, status: dict, info: dict, galileo: dict, pose: dict,
               fresh: bool = True) -> None:
        snap = self._snapshot
        snap.status = status
        snap.info = info
        snap.galileo = galileo
        snap.pose = pose
        if fresh:
            snap.recv_ts = time.monotonic()
            snap.last_error = None
            snap.consecutive_failures = 0
        else:
            # 部分成功：字段更新了，但整体新鲜度不刷新，避免"半坏网络显示 0s 在线"
            snap.last_error = "部分数据过期"
        snap.poll_count += 1

    def mark_failure(self, error: str) -> None:
        snap = self._snapshot
        snap.last_error = error
        snap.consecutive_failures += 1

    @property
    def online(self) -> bool:
        """链路在线：最近一次成功且在阈值内（默认 5s；X30 适配器另有 30s）。"""
        return bool(self._snapshot.recv_ts) and self._snapshot.age_s <= self.offline_after_s

    def as_dict(self) -> dict[str, Any]:
        snap = self._snapshot
        return {
            "status": snap.status,
            "info": snap.info,
            "galileo": snap.galileo,
            "pose": snap.pose,
            "recv_ts": snap.recv_ts,
            "age_s": snap.age_s,
            "online": self.online,
            "consecutive_failures": snap.consecutive_failures,
            "last_error": snap.last_error,
            "poll_count": snap.poll_count,
        }


cache = StateCache()
