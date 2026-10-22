"""用 HTTP 模拟器测 JCROB 适配器（真机到场前的最近似验证）。

意义：fixture 只测解析，测不到 HTTP 路径/编码/错误码；
这里起一个按真机 3546 路径响应的模拟器，适配器走完整 HTTP 链路。
真机到场后只需换 base_url，同一套断言继续用。
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from http.server import ThreadingHTTPServer

import tools_sim_jcrob as sim
from app.adapters.jcrob import HttpJcrobAdapter


@pytest.fixture()
def sim_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), sim.Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.3)
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


def _adapter(base: str) -> HttpJcrobAdapter:
    return HttpJcrobAdapter(base_url=base, username="", password="", token="",
                            timeout=5.0, angle_unit="auto")


def test_status_info_pose_over_http(sim_server):
    asyncio.run(_status_info_pose(sim_server))


async def _status_info_pose(sim_server):
    a = _adapter(sim_server)
    status = await a.get_status()
    assert status["status"] == "Free"

    info = await a.get_info()
    assert info["battery"] >= 5

    pose = await a.get_pose()
    assert isinstance(pose["x"], float) and isinstance(pose["y"], float)
    assert pose["angle_deg"] is not None

    maps = await a.list_maps()
    assert maps and maps[0]["name"] == "map1"

    png = await a.get_map_png("map1")
    assert png[:4] == b"\x89PNG"


def test_dispatch_and_cancel(sim_server):
    asyncio.run(_dispatch_and_cancel(sim_server))


async def _dispatch_and_cancel(sim_server):
    a = _adapter(sim_server)
    res = await a.dispatch({"orderId": "T-1", "actions": [
        {"actionType": "nav", "actionParameters": [{"key": "x", "value": 1.0},
                                                   {"key": "y", "value": 2.0},
                                                   {"key": "yaw", "value": 0.5}]},
        {"actionType": "photo", "actionParameters": []},
    ]})
    assert res["state"] == "RUNNING" and res["id"]

    tasks = await a.get_tasks()
    rows = tasks["tasks"] if isinstance(tasks, dict) else tasks
    assert rows and rows[0]["state"] in ("RUNNING", "COMPLETE")

    cancelled = await a.cancel()
    assert isinstance(cancelled, dict)
