"""云台预置位：URL/请求体正确性（假 ISAPI 客户端）+ 接口错误映射。"""

from __future__ import annotations

from app.services import ptz_presets


class _Resp:
    def __init__(self, code: int = 200, text: str = ""):
        self.status_code = code
        self.text = text


class _FakeClient:
    def __init__(self, calls):
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        self.calls.append(("GET", url, None))
        return _Resp(200, "<PTZPresets><PTZPreset><id>1</id><name>泵房机位</name></PTZPreset>"
                          "<PTZPreset><id>2</id><name>配电柜A</name></PTZPreset></PTZPresets>")

    def put(self, url, content=None, headers=None):
        self.calls.append(("PUT", url, content))
        return _Resp(200)

    def delete(self, url):
        self.calls.append(("DELETE", url, None))
        return _Resp(200)


def _patch(monkeypatch, calls):
    monkeypatch.setattr(ptz_presets.ptz, "available", lambda: (True, ""))
    monkeypatch.setattr(ptz_presets.ptz, "_cfg", lambda: {"enabled": True, "host": "cam",
                                                         "user": "u", "pwd": "p", "channel": 1})
    monkeypatch.setattr(ptz_presets.ptz, "_client", lambda c: _FakeClient(calls))


def test_list_parses_presets(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    ok, why, items = ptz_presets.list_presets()
    assert ok and why == ""
    assert items == [{"preset_id": 1, "name": "泵房机位"},
                     {"preset_id": 2, "name": "配电柜A"}]
    assert calls[0][1].endswith("/ISAPI/PTZCtrl/channels/1/presets")


def test_save_and_goto_and_delete(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    assert ptz_presets.save_preset(3, "新机位")[0]
    assert ptz_presets.goto_preset(3)[0]
    assert ptz_presets.delete_preset(3)[0]
    methods = [c[0] for c in calls]
    assert methods == ["PUT", "PUT", "DELETE"]
    assert "/presets/3" in calls[0][1]
    assert "<name>新机位</name>".encode() in calls[0][2]
    assert calls[1][1].endswith("/presets/3/goto")


def test_api_lists_and_reports_error(auth_client, monkeypatch):
    monkeypatch.setattr("app.api.v1.ptz_presets.presets.list_presets",
                        lambda: (True, "", [{"preset_id": 1, "name": "A"}]))
    r = auth_client.get("/api/v1/ptz/presets")
    assert r.status_code == 200 and r.json()["items"][0]["name"] == "A"

    monkeypatch.setattr("app.api.v1.ptz_presets.presets.goto_preset",
                        lambda pid: (False, "HTTP 403"))
    r2 = auth_client.post("/api/v1/ptz/presets/1/goto")
    assert r2.status_code == 400 and r2.json()["code"] == "PTZ_FAILED"
