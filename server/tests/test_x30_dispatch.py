"""X30 多点下发回归：每个带坐标的动作都要各自下一次 1003（不能只发第一个）。"""

from __future__ import annotations

import asyncio

from app.adapters.deeprobotics.adapter import DeepRoboticsX30Adapter


class _FakeClient:
    def __init__(self):
        self.goals = []
        self.port = 30000
        self.last_magic = b""

    def nav_goal(self, x, y, yaw, map_id=1):
        self.goals.append((x, y, yaw))
        return {"ok": 1}

    def nav_status(self):
        return {"Status": "0"}


def test_x30_executes_every_point():
    a = DeepRoboticsX30Adapter.__new__(DeepRoboticsX30Adapter)
    a.client = _FakeClient()

    async def _call(fn, *args, **kw):
        return fn(*args, **kw)

    a._call = _call  # type: ignore[method-assign]

    order = {"orderId": "T1", "actions": [
        {"actionType": "photo", "actionParameters": [
            {"key": "x", "value": 1.0}, {"key": "y", "value": 2.0}, {"key": "yaw", "value": 0}]},
        {"actionType": "wait", "actionParameters": [
            {"key": "x", "value": 3.0}, {"key": "y", "value": 4.0}, {"key": "yaw", "value": 0}]},
    ]}
    asyncio.run(a._execute_order(order))
    assert a.client.goals == [(1.0, 2.0, 0.0), (3.0, 4.0, 0.0)]


def test_x30_dispatch_returns_running_immediately():
    a = DeepRoboticsX30Adapter.__new__(DeepRoboticsX30Adapter)
    a.client = _FakeClient()

    async def _call(fn, *args, **kw):
        return fn(*args, **kw)

    a._call = _call  # type: ignore[method-assign]
    out = a.dispatch({"orderId": "T2", "actions": [
        {"actionType": "nav", "actionParameters": [
            {"key": "x", "value": 0}, {"key": "y", "value": 0}]}]})
    assert out["state"] == "RUNNING", out
