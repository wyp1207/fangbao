"""后台循环的可重启外壳。

单进程里任何一个循环静默死掉都不会有人发现（比如 ws_listener 挂了只剩 HTTP），
所以每个循环都必须包一层：异常 -> 记录 -> 退避 -> 重启，并上报存活时间。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

log = logging.getLogger(__name__)


class Service:
    def __init__(self, name: str, factory: Callable[[], Awaitable[None]],
                 *, backoff_s: float = 2.0, max_backoff_s: float = 30.0) -> None:
        self.name = name
        self._factory = factory
        self._task: asyncio.Task | None = None
        self._backoff = backoff_s
        self._max_backoff = max_backoff_s
        self.started_at: float = 0.0
        self.last_ok: float = 0.0
        self.restarts: int = 0
        self.last_error: str | None = None
        self._stopping = False

    async def _run(self) -> None:
        delay = self._backoff
        while not self._stopping:
            try:
                await self._factory()
                delay = self._backoff  # 正常返回也算一轮
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 任何异常都不能让循环停掉
                self.restarts += 1
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.exception("后台循环 %s 异常，%.0fs 后重启（第 %d 次）",
                              self.name, delay, self.restarts)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._max_backoff)

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopping = False
        self.started_at = time.monotonic()
        self._task = asyncio.create_task(self._run(), name=f"svc:{self.name}")

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    def health(self) -> dict:
        running = bool(self._task and not self._task.done())
        return {
            "name": self.name,
            "running": running,
            "uptime_s": round(time.monotonic() - self.started_at, 1) if self.started_at else 0,
            "restarts": self.restarts,
            "last_error": self.last_error,
        }


class LoopLagMonitor:
    """事件循环延迟：任何同步阻塞（读大 PNG、导出、同步驱动）都会先在这里露头。"""

    def __init__(self, interval: float = 0.5) -> None:
        self.interval = interval
        self.lag_ms: float = 0.0
        self._task: asyncio.Task | None = None

    async def _run(self) -> None:
        while True:
            start = time.monotonic()
            await asyncio.sleep(self.interval)
            spent = (time.monotonic() - start) * 1000
            self.lag_ms = round(max(0.0, spent - self.interval * 1000), 1)

    def start(self) -> None:
        if not self._task or self._task.done():
            self._task = asyncio.create_task(self._run(), name="loop-lag")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
