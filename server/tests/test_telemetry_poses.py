"""历史位姿接口：返回升序、跳变已过滤、带距离；空库不 500。"""

from __future__ import annotations


def test_poses_empty_ok(auth_client):
    r = auth_client.get("/api/v1/telemetry/poses", params={"hours": 24, "robot_id": 999999})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 0 and body["points"] == []


def test_poses_shape_and_order(auth_client):
    r = auth_client.get("/api/v1/telemetry/poses", params={"hours": 48, "points": 100})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) >= {"count", "points", "distance_m"}
    pts = body["points"]
    if pts:
        assert all({"ts", "x", "y", "theta"} <= set(p) for p in pts)
        ts = [p["ts"] for p in pts]
        assert ts == sorted(ts), "位姿必须按时间升序"
