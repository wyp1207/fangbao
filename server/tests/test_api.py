def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_login_and_me(client):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "admin"
    assert body["csrf_token"]

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "admin"


def test_login_wrong_password(client):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "nope"})
    assert r.status_code == 401
    assert r.json()["code"] == "UNAUTHORIZED"


def test_status_requires_login(client):
    client.cookies.clear()
    r = client.get("/api/v1/robots/1/status")
    assert r.status_code == 401


def test_status_after_login(auth_client):
    r = auth_client.get("/api/v1/robots/1/status")
    assert r.status_code == 200
    body = r.json()
    assert "online" in body and "age_s" in body and "pose" in body


def test_maps_endpoint(auth_client):
    r = auth_client.get("/api/v1/robots/1/maps")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list) and body
    assert body[0]["name"] == "map1"


def test_nav_points_are_parsed_server_side(auth_client):
    r = auth_client.get("/api/v1/robots/1/nav-points")
    assert r.status_code == 200
    body = r.json()
    assert len(body["points"]) == 6
    assert "theta_rad" in body["points"][0]
    assert body["path_data"]  # 原文保留，写回时用


def test_alarms_list_and_ack(auth_client):
    r = auth_client.get("/api/v1/alarms")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict) and "items" in body

    # 伪造一条：确认接口对不存在的 id 返回 404，而不是静默成功
    miss = auth_client.post("/api/v1/alarms/999999/ack")
    assert miss.status_code == 404


def test_alarm_flow_via_api(auth_client):
    # 直接往 store 里造一条真实规则产生的告警（电量低），走完 列表 -> 确认 的链路
    store = auth_client.app.state.alarms
    store.evaluate(status={}, info={"battery": 5, "driver_port": False}, age_s=0)

    items = auth_client.get("/api/v1/alarms").json()["items"]
    assert items and items[0]["metric"] == "battery"
    alarm_id = items[0]["id"]

    acked = auth_client.post(f"/api/v1/alarms/{alarm_id}/ack").json()
    assert acked["acked_by"] == "admin"
    assert acked["acked_at"]

    active = auth_client.get("/api/v1/alarms?status=unacked").json()["items"]
    assert all(a["id"] != alarm_id for a in active)


def test_probe_requires_csrf(client):
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    # 不带 X-CSRF-Token
    r = client.post("/api/v1/robots/1/probe")
    assert r.status_code == 403
    assert r.json()["code"] == "CSRF_FAILED"


def test_probe_with_csrf(auth_client):
    r = auth_client.post("/api/v1/robots/1/probe")
    assert r.status_code == 200
    assert r.json()["supports"]["info"] is True


def test_deep_health(auth_client):
    r = auth_client.get("/api/v1/health/deep")
    assert r.status_code == 200
    body = r.json()
    assert "cache" in body and "services" in body
    assert any(s["name"] == "status_poller" for s in body["services"])


def test_notify_channel_validation(auth_client):
    """通道类型/必填项校验：坏数据要 400，不要落库。"""
    bad_type = auth_client.post("/api/v1/notify/channels",
                                json={"name": "x", "type": "sms", "config": {}})
    assert bad_type.status_code == 400

    no_url = auth_client.post("/api/v1/notify/channels",
                              json={"name": "x", "type": "wecom", "config": {}})
    assert no_url.status_code == 400

    no_smtp = auth_client.post("/api/v1/notify/channels",
                               json={"name": "x", "type": "email", "config": {}})
    assert no_smtp.status_code == 400


def test_notify_channel_flow(auth_client):
    """建通道 → 列表里能看到 → 配置里的 URL 被打码 → 删除。"""
    r = auth_client.post("/api/v1/notify/channels", json={
        "name": "值班群", "type": "wecom",
        "config": {"url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdefgh12345678"},
        "min_level": "warn", "min_interval_min": 5,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "值班群"
    assert "***" in body["config"]["url"]          # 不能把 key 原样吐出来

    listed = auth_client.get("/api/v1/notify/channels").json()
    assert any(c["id"] == body["id"] for c in listed)

    # 测试发送指向一个必然连不上的地址：应该返回 ok=False 而不是抛 500
    r = auth_client.post(f"/api/v1/notify/channels/{body['id']}/test")
    assert r.status_code == 200
    assert r.json()["ok"] is False

    assert auth_client.delete(f"/api/v1/notify/channels/{body['id']}").status_code == 200
    assert all(c["id"] != body["id"] for c in auth_client.get("/api/v1/notify/channels").json())


def test_notify_logs_endpoint(auth_client):
    r = auth_client.get("/api/v1/notify/logs?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert "total" in body and isinstance(body["items"], list)
