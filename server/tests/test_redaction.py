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


def test_uvicorn_access_log_masks_query_token():
    """uvicorn 的 access logger 不走 root handler，必须单独挂脱敏。

    AI 回调允许 `?token=xxx`（盒子/浏览器好验证），访问日志会原样带出查询串，
    不脱敏等于把共享令牌逐行写进日志。

    注意：uvicorn 的 AccessFormatter 直接解包 record.args（5 项）来拼 request_line，
    所以脱敏只能替换 args 里的 full_path，不能改成"整行 message"——那样 logger
    会格式化失败、整条访问日志丢失（等于既丢审计又没脱敏）。
    """
    import logging

    from app.core.logging import install_request_log_redaction

    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("uvicorn.access")
    handler = _Capture()
    old_level, old_propagate = logger.level, logger.propagate
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    try:
        install_request_log_redaction()
        logger.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "POST",
                    "/api/v1/ai/callback/box-1?token=super-secret-token", "1.1", 200)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        logger.propagate = old_propagate

    assert records, "access logger 没有产出记录"
    record = records[0]

    # 1) args 结构必须保持 uvicorn AccessFormatter 能解包
    client_addr, method, full_path, http_version, status_code = record.args
    assert (client_addr, method, http_version, status_code) == (
        "127.0.0.1:5000", "POST", "1.1", 200)
    # 2) 查询串里的令牌被盖掉
    assert "super-secret-token" not in full_path
    assert "token=***" in full_path
    # 3) 拼出来的整行也不含令牌
    assert "super-secret-token" not in record.getMessage()
