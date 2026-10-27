"""把协程放到"服务端主事件循环"里跑。

为什么需要：适配器里的 httpx.AsyncClient 第一次请求时会绑定当前事件循环。
同步路由（def）跑在线程池里，直接 asyncio.run 会新建一个循环，
再用共享适配器就报 "Event ... is bound to a different event loop"。
所以统一走这里：有主循环就 run_coroutine_threadsafe，没有才自己开一个。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Coroutine, TypeVar

log = logging.getLogger(__name__)
T = TypeVar("T")

_LOOP: asyncio.AbstractEventLoop | None = None


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _LOOP
    _LOOP = loop


def run_async(coro: Coroutine[Any, Any, T], timeout: float = 60.0) -> T:
    loop = _LOOP
    if loop is not None and loop.is_running():
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if current is loop:
            # 已经在主循环里（async 路由）：不能阻塞等待自己，退化成新建循环执行
            # 这种情况只应出现在测试里；生产路径都是同步路由。
            log.warning("run_async 在主循环内被调用，退化为独立循环")
            return asyncio.run(coro)
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)
    return asyncio.run(coro)
