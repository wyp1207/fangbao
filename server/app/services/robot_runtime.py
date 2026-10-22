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
    clock_skew_s: float | None = None     # 机器人时间 - 平台时间（秒）

    def status(self) -> dict:
        snap = self.cache.as_dict()
        return {
            "robot_id": self.robot_id,
            "name": self.name,
            "online": snap["online"],
            "age_s": snap["age_s"],
            "last_error": self.error or snap["last_error"],
            "clock_skew_s": self.clock_skew_s,
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
                # 并行取四路：串行时最坏 4×超时会把"在线"打成"离线"
                import asyncio as _aio

                results = await _aio.gather(
                    rt.adapter.get_status(), rt.adapter.get_info(),
                    rt.adapter.get_galileo(), rt.adapter.get_pose(),
                    return_exceptions=True,
                )
                if all(isinstance(r, Exception) for r in results):
                    raise results[0]
                prev = rt.cache.as_dict()
                keys = ("status", "info", "galileo", "pose")
                merged = {
                    k: (prev.get(k) or {}) if isinstance(results[i], Exception) else results[i]
                    for i, k in enumerate(keys)
                }
                fresh = not any(isinstance(r, Exception) for r in results)
                rt.cache.update(**merged, fresh=fresh)
                status, info, galileo = merged["status"], merged["info"], merged["galileo"]
                rt.error = None
                rt.clock_skew_s = self._check_clock(rt, status, info, galileo)
                if self._alarms is not None:
                    self._alarms.evaluate(
                        status=status, info=info,
                        age_s=rt.cache.as_dict()["age_s"], robot_id=rt.robot_id,
                        offline_after_s=getattr(rt.adapter, "offline_after_s", None))
            except jerr.JcrobError as exc:
                rt.cache.mark_failure(exc.code)
                rt.error = exc.code
                if self._alarms is not None:
                    self._alarms.evaluate(status={}, info={},
                                          age_s=rt.cache.as_dict()["age_s"],
                                          robot_id=rt.robot_id,
                                          offline_after_s=getattr(rt.adapter, "offline_after_s", None))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                rt.cache.mark_failure(exc.__class__.__name__)
                rt.error = f"{exc.__class__.__name__}: {exc}"
                log.exception("设备 %s 轮询异常", rt.name)
            await asyncio.sleep(interval)

    def _check_clock(self, rt: RobotRuntime, status: dict, info: dict, galileo: dict) -> float | None:
        """机器人上报时间 vs 平台时间。

        JCROB 不同固件字段名不一样，这里按常见键名找；找不到就返回 None
        （= 无法核对，不是"没有偏差"），页面显示「未上报时间」。
        """
        raw = None
        for src in (status, info, galileo):
            if not isinstance(src, dict):
                continue
            for key in ("timestamp", "time", "ts", "now", "server_time"):
                if key in src and src[key] is not None:
                    raw = src[key]
                    break
            if raw is not None:
                break
        if raw is None:
            return None

        import datetime as _dt

        robot_ts = None
        if isinstance(raw, (int, float)):
            v = float(raw)
            robot_ts = v / 1000 if v > 1e11 else v       # 毫秒/秒都兼容
        elif isinstance(raw, str):
            try:
                robot_ts = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
            except ValueError:
                return None
        if robot_ts is None:
            return None

        skew = round(robot_ts - _dt.datetime.now().timestamp(), 1)
        try:
            from app.api.v1.settings import load_all
            limit = float(load_all().get("clock.max_skew_s", 2))
        except Exception:  # noqa: BLE001
            limit = 2.0
        if abs(skew) > limit and self._alarms is not None:
            self._alarms.raise_external(
                metric=f"clock_skew_{rt.robot_id}", level="warn",
                message=f"{rt.name} 时钟偏差 {skew:+.1f}s（超过 {limit:g}s），"
                        f"录像/告警/遥测时间会对不齐",
            )
        return skew

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
