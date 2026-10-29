"""云台接口：方向校验、未启用时的明确报错（不打真机）。"""

from __future__ import annotations


def test_ptz_move_rejects_bad_direction(auth_client):
    auth_client.put("/api/v1/settings", json={"values": {"ptz.enabled": True,
                                                        "ptz.host": "127.0.0.1",
                                                        "ptz.username": "u",
                                                        "ptz.password": "p"}})
    try:
        r = auth_client.post("/api/v1/ptz/move", json={"direction": "sideways"})
        assert r.status_code == 400, r.text
        assert r.json().get("code") == "BAD_DIRECTION"
    finally:
        auth_client.put("/api/v1/settings", json={"values": {"ptz.enabled": False}})


def test_ptz_disabled_gives_clear_error(auth_client):
    auth_client.put("/api/v1/settings", json={"values": {"ptz.enabled": False}})
    r = auth_client.post("/api/v1/ptz/move", json={"direction": "up"})
    assert r.status_code == 400, r.text
    assert "未启用" in r.json().get("message", "") or "PTZ" in r.json().get("code", "")
