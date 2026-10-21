from app.adapters.jcrob.config_view import project_config
from app.core.redaction import redact_obj, redact_text, redact_url


def test_redact_url_removes_token():
    url = "http://robot:3546/api/v1/system/info?token=SECRET&x=1"
    out = redact_url(url)
    assert "SECRET" not in out
    assert "token=***" in out


def test_redact_text_removes_password():
    out = redact_text("GET /token?username=admin&password=P%40ss")
    assert "P%40ss" not in out
    assert "password=***" in out


def test_redact_obj_keeps_key():
    out = redact_obj({"wifi_ssid": "abc", "wifi_password": "p", "battery": 80})
    assert out["wifi_ssid"] == "***"
    assert out["wifi_password"] == "***"
    assert out["battery"] == 80


def test_redact_nested_list():
    out = redact_obj([{"token": "t"}, {"x": 1}])
    assert out[0]["token"] == "***"
    assert out[1]["x"] == 1


def test_project_config_drops_credentials():
    raw = {
        "default_map": "map1", "auto_charge": True, "lf_linear_v": 0.6,
        "wifi_ssid": "w", "wifi_password": "p", "lagrange_id": "s", "weixin_id": "x",
    }
    view = project_config(raw)
    assert set(view) == {"default_map", "auto_charge", "lf_linear_v"}


def test_project_config_on_non_dict():
    assert project_config(None) == {}
    assert project_config([1, 2]) == {}
