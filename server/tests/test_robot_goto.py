"""点哪去哪：写开关、地图范围、距离确认、离线拒绝。"""

from __future__ import annotations

import pytest

from app.db.session import Base, SessionLocal, engine
from app.models.map_library import PlatformMap


def _write(auth_client, on: bool):
    auth_client.put("/api/v1/settings", json={"values": {"robot.write_enabled": on}})


@pytest.fixture()
def demo_map():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        m = db.query(PlatformMap).first()
        if m is None:
            m = PlatformMap(name="test-map", floor="1F", station="tests",
                            image_path="missing.png", resolution=0.05,
                            origin_x=-10, origin_y=-8, width=900, height=600,
                            is_active=True)
            db.add(m)
            db.commit()
            db.refresh(m)
        mid = m.id
    yield mid


class _FakeCache:
    def as_dict(self):
        return {"online": True, "status": {"estop": False}, "info": {"battery": 80},
                "pose": {"x": 0.0, "y": 0.0, "theta_rad": 0.0}}


class _FakeAdapter:
    def goto(self, x, y, yaw=0.0):
        return {"ok": True, "x": x, "y": y}

    async def _noop(self):
        return None


class _FakeRuntime:
    adapter = _FakeAdapter()
    cache = _FakeCache()


def test_goto_requires_write_switch(auth_client, demo_map):
    _write(auth_client, False)
    r = auth_client.post("/api/v1/robots/1/goto", json={"x": 1, "y": 1})
    assert r.status_code == 403, r.text


def test_goto_rejects_outside_map(auth_client, demo_map):
    _write(auth_client, True)
    try:
        r = auth_client.post("/api/v1/robots/1/goto", json={"x": 999, "y": 999})
        assert r.status_code == 409, r.text
        assert r.json().get("code") == "POINT_INVALID", r.text
    finally:
        _write(auth_client, False)


def test_goto_needs_confirm_when_far(auth_client, demo_map, monkeypatch):
    from app.services import robot_runtime

    monkeypatch.setattr(robot_runtime.registry, "get", lambda rid: _FakeRuntime())
    _write(auth_client, True)
    try:
        r = auth_client.post("/api/v1/robots/1/goto",
                             json={"x": 2, "y": 2, "max_m": 0.5})
        assert r.status_code == 409, r.text
        assert r.json().get("code") == "NEED_CONFIRM", r.text

        r2 = auth_client.post("/api/v1/robots/1/goto",
                              json={"x": 2, "y": 2, "max_m": 0.5, "confirmed": True})
        assert r2.status_code == 200, r2.text
        assert r2.json()["accepted"] is True
    finally:
        _write(auth_client, False)
