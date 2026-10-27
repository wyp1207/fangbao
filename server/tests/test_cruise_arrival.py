"""到点三值判定测试（C 项）：arrived / suspect / failed。"""

from __future__ import annotations

import threading

import pytest

from app.services import cruise as cruise_mod


class _Stop(threading.Event):
    pass


class _FakeAdapter:
    """按预设返回导航状态和位姿，测判定逻辑用。"""

    def __init__(self, state: str, pose: dict | None):
        self._state = state
        self._pose = pose

    def get_order(self):
        return {"state": self._state}

    def get_pose(self):
        return self._pose


def _runner() -> cruise_mod.CruiseRunner:
    return cruise_mod.CruiseRunner(session_factory=lambda: None)


@pytest.mark.parametrize(
    ("dist", "expect"),
    [
        (0.5, "arrived"),   # 容差内
        (1.5, "suspect"),   # 超容差但没到 2.5 倍 → 疑似定位漂移
        (4.0, "failed"),    # 2.5 倍以上 → 失败
    ],
)
def test_arrival_three_states(dist, expect):
    pose = {"x": dist, "y": 0.0}
    adapter = _FakeAdapter("FINISHED", pose)
    result, reason = _runner()._wait_arrival(adapter, _Stop(), target=(0.0, 0.0), radius=1.0)
    assert result == expect, (result, reason)
    if expect == "suspect":
        assert "定位" in reason


def test_failed_state_passthrough():
    result, reason = _runner()._wait_arrival(_FakeAdapter("FAILED", None), _Stop(),
                                            target=(0.0, 0.0), radius=1.0)
    assert result == "failed" and "无法到达" in reason


def test_capabilities_default_to_waypoint():
    """B：能力协商——未确认支持整单的适配器必须是逐点。"""
    from app.adapters.deeprobotics.adapter import DeepRoboticsX30Adapter
    from app.adapters.jcrob.http_adapter import HttpJcrobAdapter

    for cls in (DeepRoboticsX30Adapter, HttpJcrobAdapter):
        caps = getattr(cls, "capabilities", {})
        assert caps.get("supports_batch") is False
        assert caps.get("supports_inline_actions") is False
