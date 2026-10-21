"""status_poller：每 1s 拉 status/info/galileo/pose 写进缓存，并顺带求值告警。

W1 只用 HTTP 轮询；WS 监听等真机拿到实际频率再接（见 docs/真机取数清单.md D26/D29）。
"""

from __future__ import annotations

import asyncio
import logging

from app.adapters.jcrob import errors as jerr
from app.services.alarms import AlarmStore
from app.services.state_cache import StateCache

log = logging.getLogger(__name__)


class StatusPoller:
    def __init__(self, adapter, cache: StateCache, interval: float = 1.0,
                 alarms: AlarmStore | None = None) -> None:
        self.adapter = adapter
        self.cache = cache
        self.interval = interval
        self.alarms = alarms or AlarmStore()

    async def run_once(self) -> None:
        """一次采样。任何一路失败都不写缓存，只累计失败次数并参与离线判定。"""
        try:
            status = await self.adapter.get_status()
            info = await self.adapter.get_info()
            galileo = await self.adapter.get_galileo()
            pose = await self.adapter.get_pose()
        except jerr.JcrobError as exc:
            self.cache.mark_failure(exc.code)
            self.alarms.evaluate(status={}, info={}, age_s=self.cache.as_dict()["age_s"])
            log.warning("轮询失败: %s", exc.code)
            return

        self.cache.update(status=status, info=info, galileo=galileo, pose=pose)
        self.alarms.evaluate(status=status, info=info, age_s=0.0)

    async def __call__(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(self.interval)
