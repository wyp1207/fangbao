"""SDK 测温/抓拍解析测试（不连真机）。"""

from __future__ import annotations

import asyncio

from app.adapters.jcrob.http_adapter import HttpJcrobAdapter


class _FakeClient:
    def __init__(self, payload):
        self.payload = payload

    async def get(self, path, params=None):
        return self.payload


def _adapter(payload) -> HttpJcrobAdapter:
    a = HttpJcrobAdapter(base_url="http://127.0.0.1:3546", username="u", password="p")
    a.client = _FakeClient(payload)  # type: ignore[assignment]
    return a


def test_temperature_parses_common_field_names():
    for payload in (
        {"max": 41.5, "min": 20.1, "avg": 28.0},
        {"maxTemp": 41.5, "minTemp": 20.1, "avgTemp": 28.0},
        {"points": [{"temp": 20.1}, {"temp": 41.5}]},
    ):
        out = asyncio.run(_adapter(payload).get_camera_temperature())
        assert out.get("max") == 41.5, payload


def test_temperature_without_value_returns_raw_only():
    out = asyncio.run(_adapter({"foo": 1}).get_camera_temperature())
    assert "max" not in out
    assert out["raw"] == {"foo": 1}


def test_snapshot_rejects_missing_location():
    import pytest

    from app.adapters.jcrob import errors as jerr

    with pytest.raises(jerr.NotSupported):
        asyncio.run(_adapter({}).camera_snapshot())


def test_ir_temp_sensor_kind_exists():
    from app.api.v1.sensors import KINDS

    assert KINDS["ir_temp"]["unit"] == "℃"
    assert KINDS["lux"]["unit"] == "lux"
