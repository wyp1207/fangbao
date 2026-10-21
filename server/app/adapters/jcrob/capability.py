"""能力探测：启动时按顺序试，缺什么就标 false，不阻塞只读功能。

输出结构与 docs/平台方案-定稿.md §5.4 一致。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.adapters.jcrob import errors as jerr

log = logging.getLogger(__name__)


async def probe(adapter) -> dict[str, Any]:
    capabilities: dict[str, Any] = {
        "version": "unknown",
        "slam_type": "unknown",
        "port": None,
        "supports": {
            "info": False,
            "config": False,
            "loop_task": False,
            "task_callback": False,
            "nav_points": False,
            "multi_map": False,
            "onvif": False,
            "self_test": False,
        },
        "errors": {},
        "probed_at": datetime.now(timezone.utc).isoformat(),
    }

    async def attempt(name: str, coro, on_ok=None) -> Any:
        try:
            value = await coro
            capabilities["supports"][name] = True
            if on_ok:
                on_ok(value)
            return value
        except jerr.JcrobError as exc:
            capabilities["errors"][name] = exc.code
            log.warning("能力探测失败 %s: %s", name, exc.code)
            return None

    def take_info(info: dict) -> None:
        inner = info.get("info") or {}
        capabilities["version"] = inner.get("version") or "unknown"
        capabilities["port"] = inner.get("port")
        capabilities["slam_type"] = info.get("slam_type") or "unknown"

    await attempt("info", adapter.get_info(), take_info)
    await attempt("config", adapter.get_config_view())
    await attempt("self_test", adapter.get_self_test())

    maps = await attempt("saved_maps", adapter.list_maps())
    if isinstance(maps, list) and maps:
        capabilities["supports"]["multi_map"] = len(maps) > 1
        if capabilities["slam_type"] in (None, "unknown"):
            sample = maps[0] if isinstance(maps[0], dict) else {}
            capabilities["slam_type"] = sample.get("slam_type") or sample.get("map_type") or "unknown"

    points = await attempt("nav_points", adapter.get_nav_points())
    if isinstance(points, dict) and points.get("path_data"):
        capabilities["supports"]["nav_points"] = True

    tasks = await attempt("task", adapter.get_tasks())
    if isinstance(tasks, list):
        capabilities["supports"]["task_callback"] = True

    loop = await attempt("loop_task", adapter.get_loop_task())
    if loop is not None:
        capabilities["supports"]["loop_task"] = True

    actions = await attempt("action", adapter.get_actions())
    if isinstance(actions, list):
        names = {str(a.get("type", "")) for a in actions if isinstance(a, dict)}
        capabilities["supports"]["onvif"] = any(n.startswith("onvif_") for n in names)

    return capabilities
