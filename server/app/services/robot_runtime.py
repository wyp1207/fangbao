"""多机器人运行时：每台设备一个适配器 + 一份缓存 + 一个轮询任务。

为什么不是"把 1 台的循环抄 N 遍"：
- 轮询是 IO 等待型任务，用 asyncio 任务并发，不是线程；
- 每台设备有自己的缓存，前端切设备就是切数据源；
- 告警去重键要带机器人 id，否则 A 车离线会把 B 车的离线告警压掉。

行业做法（VDA5050 / Open-RMF）是机器人主动上报、平台订阅；
JCROB 目前只给 HTTP，所以先并发轮询，真机有 WS 3547 后再把
`_poll_loop` 换成订阅，缓存接口不用改。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from app.adapters.registry import AdapterNotSupported, build_for
from app.core.config import get_settings
from app.services.state_cache import StateCache

log = logging.getLogger(__name__)


@dataclass
class RobotRuntime:
    robot_id: int
    name: str
    adapter: Any = None
    cache: StateCache = field(default_factory=StateCache)
    error: str | None = None
    task: asyncio.Task | None = None

    def status(self) -> dict:
        snap = self.cache.as_dict()
        return {
            "robot_id": self.robot_id,
            "name": self.name,
            "online": snap["online"],
            "age_s": snap["age_s"],
            "last_error": self.error or snap["last_error"],
        }


class RobotRegistry:
    def __init__(self) -> None:
        self._runtimes: dict[int, RobotRuntime] = {}
        self._lock = asyncio.Lock()
        self._alarms = None

    def attach_alarms(self, alarms) -> None:
        self._alarms = alarms

    @property
    def runtimes(self) -> dict[int, RobotRuntime]:
        return self._runtimes

    def get(self, robot_id: int) -> RobotRuntime | None:
        return self._runtimes.get(robot_id)

    def default(self) -> RobotRuntime | None:
        if 1 in self._runtimes:
            return self._runtimes[1]
        return next(iter(self._runtimes.values()), None)

    async def start(self, robots: list) -> None:
        """按数据库里的设备台账起轮询任务。只有启用的设备才轮询。"""
        settings = get_settings()
        async with self._lock:
            for robot in robots:
                if not getattr(robot, "is_active", True):
                    continue
                rt = RobotRuntime(robot_id=robot.id, name=robot.name)
                try:
                    rt.adapter, _err = build_for(robot, settings=settings)
                except AdapterNotSupported as exc:
                    rt.error = f"适配器未实现：{exc.reason}"
                    log.warning("设备 %s 不轮询：%s", robot.name, exc.reason)
                    self._runtimes[robot.id] = rt
                    continue
                except Exception as exc:  # noqa: BLE001
                    rt.error = f"{exc.__class__.__name__}: {exc}"
                    self._runtimes[robot.id] = rt
                    continue
                self._runtimes[robot.id] = rt
                rt.task = asyncio.create_task(self._poll_loop(rt, settings.jcrob_poll_interval))
                log.info("开始轮询设备 %s（id=%s）", robot.name, robot.id)

    async def _poll_loop(self, rt: RobotRuntime, interval: float) -> None:
        from app.adapters.jcrob import errors as jerr

        while True:
            try:
                status = await rt.adapter.get_status()
                info = await rt.adapter.get_info()
                galileo = await rt.adapter.get_galileo()
                pose = await rt.adapter.get_pose()
                rt.cache.update(status=status, info=info, galileo=galileo, pose=pose)
                rt.error = None
                if self._alarms is not None:
                    self._alarms.evaluate(status=status, info=info, age_s=0.0,
                                          robot_id=rt.robot_id)
            except jerr.JcrobError as exc:
                rt.cache.mark_failure(exc.code)
                rt.error = exc.code
                if self._alarms is not None:
                    self._alarms.evaluate(status={}, info={},
                                          age_s=rt.cache.as_dict()["age_s"],
                                          robot_id=rt.robot_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                rt.cache.mark_failure(exc.__class__.__name__)
                rt.error = f"{exc.__class__.__name__}: {exc}"
                log.exception("设备 %s 轮询异常", rt.name)
            await asyncio.sleep(interval)

    async def stop(self) -> None:
        for rt in self._runtimes.values():
            if rt.task:
                rt.task.cancel()
        for rt in self._runtimes.values():
            if rt.task:
                try:
                    await rt.task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        self._runtimes.clear()


registry = RobotRegistry()
