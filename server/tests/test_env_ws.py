"""环境 WS 解析与落库的单元测试（不连真机）。"""

from __future__ import annotations

import json

from app.services.env_ws import FIELD_KIND, parse_payload


def test_parse_flat_payload():
    raw = json.dumps({"temperature": 26.5, "rh": 45.0, "lel": 3.2, "noise": 51.0})
    assert parse_payload(raw) == {
        "temperature": 26.5, "rh": 45.0, "lel": 3.2, "noise": 51.0,
    }


def test_parse_nested_and_list_payload():
    raw = json.dumps({"topic": "x", "data": [{"pm2_5": 18.0, "ignored": "abc"},
                                             {"smoke": 0.02}]})
    assert parse_payload(raw) == {"pm2_5": 18.0, "smoke": 0.02}


def test_parse_skips_non_numeric_and_unknown():
    raw = json.dumps({"temperature": "26.5", "co2": True, "foo": 1.0})
    assert parse_payload(raw) == {}


def test_parse_bad_json_returns_empty():
    assert parse_payload("not json") == {}
    assert parse_payload(b"\x00\x01") == {}


def test_every_field_has_a_known_kind():
    from app.api.v1.sensors import KINDS

    for field, kind in FIELD_KIND.items():
        assert kind in KINDS, f"{field} → {kind} 不在传感器类型里"
