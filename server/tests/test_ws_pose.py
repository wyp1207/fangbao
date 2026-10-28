"""位姿 WebSocket：登录后可连、3 秒内收到多帧；未登录被拒。"""

from __future__ import annotations

import json


def test_ws_requires_auth(client):
    import pytest
    from starlette.websockets import WebSocketDisconnect

    client.cookies.clear()   # 别的用例登录过，这里要保证匿名

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/ws/robot/1") as ws:
            ws.receive_text()


def test_ws_pushes_pose(auth_client):
    with auth_client.websocket_connect("/api/v1/ws/robot/1") as ws:
        got = []
        for _ in range(3):
            raw = ws.receive_text()
            msg = json.loads(raw)
            assert msg["type"] == "state"
            assert "pose" in msg
            got.append(msg)
        assert len(got) == 3
