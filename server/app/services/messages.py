"""系统消息：内存环形缓冲。

为什么不做数据库：和告警一样，这一期没有历史库（W5 才建），
消息只是"给值班的人看一眼发生了什么"，重启即清空是可以接受的。
真要追溯，去看操作日志（W5）。

谁往里写：
- 视频源注册 / 录像起停
- 用户增删改
- 告警确认
- 能力探测失败
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal

Level = Literal["info", "warn", "danger"]


@dataclass
class Message:
    id: int
    ts: float
    level: Level
    source: str          # system / video / user / alarm
    title: str
    body: str = ""
    link: dict[str, Any] = field(default_factory=dict)


class MessageStore:
    def __init__(self, capacity: int = 200) -> None:
        self._items: list[Message] = []
        self._seq = 0
        self._capacity = capacity
        self._lock = threading.Lock()

    def add(self, level: Level, source: str, title: str, body: str = "",
            link: dict[str, Any] | None = None) -> Message:
        with self._lock:
            self._seq += 1
            msg = Message(self._seq, time.time(), level, source, title, body, link or {})
            self._items.append(msg)
            if len(self._items) > self._capacity:
                self._items = self._items[-self._capacity:]
            return msg

    def list(self, limit: int = 100) -> list[Message]:
        with self._lock:
            return list(reversed(self._items[-limit:]))

    def unread(self, since_ts: float) -> int:
        with self._lock:
            return sum(1 for m in self._items if m.ts > since_ts)


store = MessageStore()
