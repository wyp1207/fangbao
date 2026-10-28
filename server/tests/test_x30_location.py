"""X30 Location 语义：0=定位正常、1=定位丢失（上一版写反了，真机抓到）。"""

from __future__ import annotations

import asyncio

from app.adapters.deeprobotics.adapter import DeepRoboticsX30Adapter


def _adapter_with(status: dict) -> DeepRoboticsX30Adapter:
    a = DeepRoboticsX30Adapter.__new__(DeepRoboticsX30Adapter)
    class _Client:
        port = 30000
        last_magic = b""

        def status(self):
            return status

        def battery(self):
            return {"BatteryLevel": "100"}

        def nav_status(self):
            return {"Status": "0"}

    a.client = _Client()

    async def _call(fn, *args, **kw):
        return status

    a._call = _call  # type: ignore[method-assign]
    return a


def test_location_zero_means_ok():
    a = _adapter_with({"MotionState": "2", "Location": "0", "PosX": "1", "PosY": "2"})
    st = asyncio.run(a.get_status())
    assert st["located"] is True


def test_location_one_means_lost():
    a = _adapter_with({"MotionState": "2", "Location": "1", "PosX": "1", "PosY": "2"})
    st = asyncio.run(a.get_status())
    assert st["located"] is False


def test_location_missing_is_unknown():
    a = _adapter_with({"MotionState": "2", "PosX": "1", "PosY": "2"})
    st = asyncio.run(a.get_status())
    assert st["located"] is None
