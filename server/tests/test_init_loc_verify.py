"""重置定位的读回校验（D3）：定位丢失/漂移/正常三种情况。"""

from __future__ import annotations

from app.api.v1.robots import verify_initial_pose


def test_ok_within_tolerance():
    r = verify_initial_pose({"located": True, "pose": {"x": 0.2, "y": -0.3}}, 0.0, 0.0)
    assert r["verified"] is True and r["distance_m"] == 0.36


def test_fails_when_not_located():
    r = verify_initial_pose({"located": False, "pose": {"x": 0.0, "y": 0.0}}, 0.0, 0.0)
    assert r["verified"] is False
    assert "定位未就绪" in r["note"]


def test_fails_when_drifted():
    r = verify_initial_pose({"located": True, "pose": {"x": 1.2, "y": 0.0}}, 0.0, 0.0)
    assert r["verified"] is False
    assert r["distance_m"] == 1.2 and "超过" in r["note"]


def test_unknown_pose_still_ok_if_located():
    """没有位姿字段的适配器：只校验 located，不瞎判失败。"""
    r = verify_initial_pose({"located": True}, 0.0, 0.0)
    assert r["verified"] is True and r["distance_m"] is None
