"""云台预置位：URL/请求体正确性（假 ISAPI 客户端）+ 编号范围/覆盖/接口错误映射。"""

from __future__ import annotations

import pytest

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


# 真实 X30 固件返回（2026-11 实测）：带 xmlns、字段顺序 enabled→id→presetName
REAL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PTZPresetList version="2.0" xmlns="http://www.std-cgi.com/ver20/XMLSchema">
<PTZPreset><enabled>true</enabled><id>3</id><presetName>右点</presetName>
<PresetPosition><positionX>0</positionX><positionY>0</positionY></PresetPosition></PTZPreset>
<PTZPreset><enabled>true</enabled><id>1</id><presetName>预置点 1</presetName></PTZPreset>
<PTZPreset><enabled>false</enabled><id>999</id><presetName>越界</presetName></PTZPreset>
</PTZPresetList>"""


def test_parse_real_isapi_xml():
    items = ptz_presets.parse_presets(REAL_XML)
    assert items == [{"preset_id": 1, "name": "预置点 1"},
                     {"preset_id": 3, "name": "右点"}]   # 按编号排序、越界丢弃


def test_parse_legacy_name_tag():
    xml = "<PTZPresets><PTZPreset><id>2</id><name>旧固件</name></PTZPreset></PTZPresets>"
    assert ptz_presets.parse_presets(xml) == [{"preset_id": 2, "name": "旧固件"}]


def test_parse_broken_xml_falls_back():
    # 根节点没闭合 → ElementTree 报错 → 正则兜底
    xml = "<PTZPresetList><PTZPreset><id>4</id><presetName>断裂</presetName>"
    assert ptz_presets.parse_presets(xml) == [{"preset_id": 4, "name": "断裂"}]


def test_save_and_goto_and_delete(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    assert ptz_presets.save_preset(3, "新机位")[0]
    assert ptz_presets.goto_preset(3)[0]
    assert ptz_presets.delete_preset(3)[0]
    methods = [c[0] for c in calls]
    assert methods == ["PUT", "PUT", "DELETE"]
    assert "/presets/3" in calls[0][1]
    assert "<presetName>新机位</presetName>".encode() in calls[0][2]
    assert calls[1][1].endswith("/presets/3/goto")


def test_next_free_id():
    assert ptz_presets.next_free_id([]) == 1
    assert ptz_presets.next_free_id([{"preset_id": 1}, {"preset_id": 3}]) == 2
    full = [{"preset_id": i} for i in range(1, 257)]
    assert ptz_presets.next_free_id(full) is None
    assert ptz_presets.next_free_id(full[:-1]) == 256


@pytest.mark.parametrize("preset_id", [0, -1, 257, 999])
def test_save_rejects_out_of_range(monkeypatch, preset_id):
    calls = []
    _patch(monkeypatch, calls)
    ok, why = ptz_presets.save_preset(preset_id, "x")
    assert not ok
    assert "1–256" in why
    assert calls == []          # 编号非法时不能打到相机


def test_goto_and_delete_reject_out_of_range(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    assert not ptz_presets.goto_preset(0)[0]
    assert not ptz_presets.delete_preset(257)[0]
    assert calls == []


def test_save_overwrites_same_id(monkeypatch):
    """同号再存 = 覆盖：请求打到同一个 /presets/{id}，PUT 语义由相机保证。"""
    calls = []
    _patch(monkeypatch, calls)
    assert ptz_presets.save_preset(2, "新名字")[0]
    assert calls[0][0] == "PUT"
    assert calls[0][1].endswith("/presets/2")
    assert "<id>2</id>".encode() in calls[0][2]


def test_name_xml_escaped(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    assert ptz_presets.save_preset(5, "A&B<C>")[0]
    body = calls[0][2]
    assert b"A&amp;B&lt;C&gt;" in body
    assert b"<C>" not in body


def test_unreachable_camera_reports_error(monkeypatch):
    monkeypatch.setattr(ptz_presets.ptz, "available", lambda: (True, ""))
    monkeypatch.setattr(ptz_presets.ptz, "_cfg", lambda: {"enabled": True, "host": "cam",
                                                         "user": "u", "pwd": "p", "channel": 1})

    def _boom(c):
        raise OSError("unreachable")

    monkeypatch.setattr(ptz_presets.ptz, "_client", _boom)
    ok, why = ptz_presets.save_preset(1, "x")
    assert not ok and "OSError" in why
    ok2, why2, items = ptz_presets.list_presets()
    assert not ok2 and items == [] and why2


def test_api_lists_and_reports_error(auth_client, monkeypatch):
    monkeypatch.setattr("app.api.v1.ptz_presets.presets.list_presets",
                        lambda: (True, "", [{"preset_id": 1, "name": "A"}]))
    r = auth_client.get("/api/v1/ptz/presets")
    assert r.status_code == 200 and r.json()["items"][0]["name"] == "A"
    assert r.json()["next_id"] == 2 and r.json()["max_id"] == 256

    monkeypatch.setattr("app.api.v1.ptz_presets.presets.goto_preset",
                        lambda pid: (False, "HTTP 403"))
    r2 = auth_client.post("/api/v1/ptz/presets/1/goto")
    assert r2.status_code == 400 and r2.json()["code"] == "PTZ_FAILED"


def test_api_rejects_bad_preset_id(auth_client):
    r = auth_client.post("/api/v1/ptz/presets", json={"preset_id": 0, "name": "x"})
    assert r.status_code == 400 and r.json()["code"] == "BAD_PRESET"
    assert "1–256" in r.json()["message"]
    r2 = auth_client.post("/api/v1/ptz/presets", json={"preset_id": "abc"})
    assert r2.status_code == 400 and r2.json()["code"] == "BAD_PRESET"


def test_api_unreachable_camera_message(auth_client, monkeypatch):
    monkeypatch.setattr("app.api.v1.ptz_presets.presets.list_presets",
                        lambda: (False, "ConnectError: refused", []))
    r = auth_client.get("/api/v1/ptz/presets")
    assert r.status_code == 200
    assert r.json()["ok"] is False and "ConnectError" in r.json()["reason"]

    monkeypatch.setattr("app.api.v1.ptz_presets.presets.save_preset",
                        lambda pid, name: (False, "ConnectError: refused"))
    r2 = auth_client.post("/api/v1/ptz/presets", json={"preset_id": 1, "name": "x"})
    assert r2.status_code == 400 and "ConnectError" in r2.json()["message"]
