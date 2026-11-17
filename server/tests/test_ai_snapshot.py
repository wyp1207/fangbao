"""AI 抓图接口：按 ai_stream 抓 ISAPI JPEG，落盘并返回地址。"""

from __future__ import annotations

import time

from app.db.session import SessionLocal
from app.models.ai import AiStream


def _mk_stream(**kw) -> int:
    """建一条流；同 (robot_id, stream_type, role) 已存在就复用，测试可重复跑。"""
    robot_id = kw.get("robot_id", 99)
    stream_type = kw.get("stream_type", "visible")
    role = kw.get("role", "main")
    with SessionLocal() as db:
        s = (db.query(AiStream)
             .filter(AiStream.robot_id == robot_id,
                     AiStream.stream_type == stream_type,
                     AiStream.role == role)
             .first())
        if s is None:
            s = AiStream(robot_id=robot_id, stream_type=stream_type, role=role)
            db.add(s)
        s.rtsp_url = kw.get("rtsp_url", "rtsp://u:p@127.0.0.1:554/x")
        s.channel = kw.get("channel", "101")
        s.status = kw.get("status", "active")
        db.commit()
        db.refresh(s)
        return s.id


def _patch_capture(monkeypatch) -> None:
    """不真的连相机：抓图返回假 JPEG，落盘返回假地址。"""
    def fake_capture(picture_url, username, password, timeout=3.0):
        assert "/ISAPI/Streaming/channels/" in picture_url
        return b"\xff\xd8" + b"x" * 2048

    def fake_save(data, stream_type):
        return {"path": f"ai_snapshots/20260101/{stream_type}.jpg",
                "url": f"/api/v1/ai/snapshots/20260101/{stream_type}.jpg",
                "bytes": len(data)}

    monkeypatch.setattr("app.services.snapshot.capture_isapi", fake_capture)
    monkeypatch.setattr("app.services.snapshot.save_ai_shot", fake_save)


def test_capture_snapshot_ok(auth_client, monkeypatch):
    sid = _mk_stream()

    def fake_capture(url, user, pwd, timeout=3.0):
        assert "ISAPI/Streaming/channels/101/picture" in url
        return b"\xff\xd8" + b"x" * 2048

    def fake_save(data, stream_type):
        return {"path": "ai_snapshots/20260101/x.jpg",
                "url": "/api/v1/ai/snapshots/20260101/x.jpg", "bytes": len(data)}

    monkeypatch.setattr("app.services.snapshot.capture_isapi", fake_capture)
    monkeypatch.setattr("app.services.snapshot.save_ai_shot", fake_save)

    r = auth_client.post("/api/v1/ai/snapshots/capture",
                         json={"stream_id": sid, "preset_id": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stream_id"] == sid
    assert body["preset_id"] == 3
    assert body["bytes"] > 1024
    assert body["result_id"]


def test_capture_inactive_stream(auth_client):
    sid = _mk_stream(robot_id=98, status="disabled")
    r = auth_client.post("/api/v1/ai/snapshots/capture", json={"stream_id": sid})
    assert r.status_code == 400
    assert r.json()["code"] == "STREAM_INACTIVE"


def test_list_streams(auth_client):
    _mk_stream(robot_id=97, stream_type="thermal", role="main", channel="201")
    r = auth_client.get("/api/v1/ai/streams?robot_id=97")
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["stream_type"] == "thermal"


# ---------- 预置位联动：转过去 → 等 dwell → 抓指定流 ----------


def test_ptz_goto_capture_ok(auth_client, monkeypatch):
    visible = _mk_stream(robot_id=2, stream_type="visible", channel="101")
    _mk_stream(robot_id=2, stream_type="thermal", channel="201")
    _patch_capture(monkeypatch)

    got: list[int] = []

    def fake_goto(preset_id):
        got.append(preset_id)
        return True, ""

    slept: list[float] = []
    monkeypatch.setattr("app.services.ptz_presets.goto_preset", fake_goto)
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))

    r = auth_client.post(
        "/api/v1/ai/ptz/goto_capture",
        json={"preset_id": 1, "dwell_s": 0, "stream_ids": [visible]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["preset_id"] == 1
    assert body["dwell_s"] == 0
    assert len(body["captures"]) == 1
    cap = body["captures"][0]
    assert cap["stream_id"] == visible
    assert cap["stream_type"] == "visible"
    assert cap["preset_id"] == 1
    assert cap["bytes"] > 1024
    assert got == [1]          # 只转了一次，且是请求里的预置位
    assert slept == []         # dwell_s=0 不该睡


def test_ptz_goto_capture_waits_dwell(auth_client, monkeypatch):
    visible = _mk_stream(robot_id=2, stream_type="visible", channel="101")
    _patch_capture(monkeypatch)
    monkeypatch.setattr("app.services.ptz_presets.goto_preset", lambda pid: (True, ""))

    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))

    r = auth_client.post(
        "/api/v1/ai/ptz/goto_capture",
        json={"preset_id": 2, "dwell_s": 2, "stream_ids": [visible]},
    )
    assert r.status_code == 200, r.text
    assert slept == [2]        # 云台到位后等 dwell 再抓


def test_ptz_goto_capture_bad_preset(auth_client, monkeypatch):
    _mk_stream(robot_id=2, stream_type="visible", channel="101")
    _patch_capture(monkeypatch)

    called: list[int] = []
    monkeypatch.setattr("app.services.ptz_presets.goto_preset",
                        lambda pid: called.append(pid) or (True, ""))
    monkeypatch.setattr(time, "sleep", lambda s: None)

    r = auth_client.post(
        "/api/v1/ai/ptz/goto_capture",
        json={"preset_id": 33, "dwell_s": 0, "stream_ids": []},
    )
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "BAD_PRESET"
    assert called == []        # 参数不合法就不该下发云台动作


def test_ptz_goto_capture_goto_failed(auth_client, monkeypatch):
    visible = _mk_stream(robot_id=2, stream_type="visible", channel="101")
    _patch_capture(monkeypatch)
    monkeypatch.setattr("app.services.ptz_presets.goto_preset",
                        lambda pid: (False, "HTTP 500: busy"))
    monkeypatch.setattr(time, "sleep", lambda s: None)

    r = auth_client.post(
        "/api/v1/ai/ptz/goto_capture",
        json={"preset_id": 1, "dwell_s": 0, "stream_ids": [visible]},
    )
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "PTZ_GOTO_FAILED"
    assert "busy" in r.json()["message"]

