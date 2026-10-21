import asyncio
from pathlib import Path

import pytest

from app.adapters.jcrob.mock_adapter import MockJcrobAdapter

FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "jcrob" / "fixtures"


@pytest.fixture
def adapter():
    return MockJcrobAdapter(FIXTURES, angle_unit="deg")


def test_pose_is_normalized_to_radians(adapter):
    pose = asyncio.run(adapter.get_pose())
    assert set(pose) >= {"x", "y", "angle_deg", "theta_rad"}
    assert pivot_ok(pose["theta_rad"], pose["angle_deg"])


def pivot_ok(theta_rad, angle_deg):
    import math

    return abs(math.degrees(theta_rad) - angle_deg) < 1e-6


def test_galileo_current_angle_rad(adapter):
    galileo = asyncio.run(adapter.get_galileo())
    assert galileo["angle_unit"] == "deg"
    assert pivot_ok(galileo["currentAngle_rad"], galileo["currentAngle"])


def test_config_view_drops_wifi(adapter):
    view = asyncio.run(adapter.get_config_view())
    assert "wifi_password" not in view
    assert view["default_map"] == "map1"


def test_maps_fixture_shape(adapter):
    maps = asyncio.run(adapter.list_maps())
    assert len(maps) == 1
    assert maps[0]["resolution"] > 0
    assert len(maps[0]["origin"]) == 3


def test_capabilities_probe(adapter):
    caps = asyncio.run(adapter.probe_capabilities())
    assert caps["version"] == "6.1.5"
    assert caps["slam_type"] == "camera"
    assert caps["supports"]["info"] is True
    assert caps["supports"]["nav_points"] is True


def test_nav_points_parse_via_adapter(adapter):
    from app.adapters.jcrob.units import parse_nav_points

    payload = asyncio.run(adapter.get_nav_points())
    points = parse_nav_points(payload["path_data"])
    assert len(points) == 6
    assert all(-7.7 < p["x"] < 7.7 for p in points)
