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


def test_password_policy(auth_client):
    """密码策略：太短/纯数字要被拒，合规的能改，改回原样。"""
    short = auth_client.post("/api/v1/auth/password",
                             json={"old_password": "admin123", "new_password": "abc"})
    assert short.status_code in (400, 422)

    weak = auth_client.post("/api/v1/auth/password",
                            json={"old_password": "admin123", "new_password": "12345678"})
    assert weak.status_code == 400
    assert "字母" in weak.json()["message"] or "数字" in weak.json()["message"]

    ok = auth_client.post("/api/v1/auth/password",
                          json={"old_password": "admin123", "new_password": "Admin12345"})
    assert ok.status_code == 200

    back = auth_client.post("/api/v1/auth/password",
                            json={"old_password": "Admin12345", "new_password": "admin123"})
    assert back.status_code == 200


def test_login_lockout(auth_client):
    """连续 5 次密码错误后，第 6 次应提示锁定而不是继续普通 401。"""
    for _ in range(5):
        r = auth_client.post("/api/v1/auth/login",
                             json={"username": "lockme", "password": "wrong-pass"})
        assert r.status_code == 401
    locked = auth_client.post("/api/v1/auth/login",
                              json={"username": "lockme", "password": "wrong-pass"})
    assert locked.status_code == 401
    assert "次数过多" in locked.json()["message"]


def test_map_point_out_of_range(auth_client):
    """点位超出地图范围要被拒——这是防撞机的最后一道闸。"""
    import io as _io

    png = (b"\x89PNG\r\n\x1a\n")
    # 直接构造一张 100x100 的图太麻烦，用真实 PIL 生成
    from PIL import Image

    buf = _io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(buf, format="PNG")
    buf.seek(0)

    r = auth_client.post(
        "/api/v1/maps/library",
        files={"file": ("t.png", buf.getvalue(), "image/png")},
        data={"name": "校验用图", "resolution": "0.05", "origin_x": "0", "origin_y": "0"},
    )
    assert r.status_code == 200, r.text
    map_id = r.json()["id"]

    ok = auth_client.post(f"/api/v1/maps/library/{map_id}/points",
                          json={"name": "图内", "x": 2.0, "y": 2.0})
    assert ok.status_code == 200

    bad = auth_client.post(f"/api/v1/maps/library/{map_id}/points",
                           json={"name": "图外", "x": 99.0, "y": 99.0})
    assert bad.status_code == 400
    assert bad.json()["code"] == "POINT_OUT_OF_MAP"

    # 分辨率不合理也要拒
    buf.seek(0)
    bad_res = auth_client.post(
        "/api/v1/maps/library",
        files={"file": ("t2.png", buf.getvalue(), "image/png")},
        data={"name": "坏分辨率", "resolution": "5.0"},
    )
    assert bad_res.status_code == 400
    assert bad_res.json()["code"] == "BAD_RESOLUTION"


def test_safety_role_scope(auth_client):
    """安全管理员只能改告警类设置；运维类（录像/视频）仍归管理员。"""
    made = auth_client.post("/api/v1/users", json={
        "username": "safety_t", "password": "Safety12345", "role": "safety",
    })
    assert made.status_code == 200

    # 用安全管理员登录
    import http.cookiejar
    from fastapi.testclient import TestClient
    c2 = TestClient(auth_client.app)
    r = c2.post("/api/v1/auth/login", json={"username": "safety_t", "password": "Safety12345"})
    assert r.status_code == 200
    c2.headers.update({"X-CSRF-Token": r.json()["csrf_token"]})

    # 新账号必须先改初始密码（后端也会拦）
    assert c2.put("/api/v1/settings", json={"values": {"alarm.battery_warn": 21}}).status_code == 403
    changed = c2.post("/api/v1/auth/password",
                      json={"old_password": "Safety12345", "new_password": "Safety67890"})
    assert changed.status_code == 200
    c2.headers.update({"X-CSRF-Token": changed.json().get("csrf_token", r.json()["csrf_token"])})

    ok = c2.put("/api/v1/settings", json={"values": {"alarm.battery_warn": 21}})
    assert ok.status_code == 200

    denied = c2.put("/api/v1/settings", json={"values": {"record.keep_days": 10}})
    assert denied.status_code == 400
    assert denied.json()["code"] == "FORBIDDEN"

    assert c2.post("/api/v1/users", json={
        "username": "x_t", "password": "Abcd12345", "role": "viewer"}).status_code == 403

    # 还原
    auth_client.put("/api/v1/settings", json={"values": {"alarm.battery_warn": 20}})


def test_task_run_flow(auth_client):
    """模板 → 计划 → 机器人回传（幂等）→ 取消规则。"""
    import io as _io
    from PIL import Image

    buf = _io.BytesIO()
    Image.new("RGB", (120, 120), "white").save(buf, format="PNG")

    m = auth_client.post(
        "/api/v1/maps/library",
        files={"file": ("t.png", buf.getvalue(), "image/png")},
        data={"name": "执行记录图", "resolution": "0.05"},
    )
    assert m.status_code == 200
    mid = m.json()["id"]

    p1 = auth_client.post(f"/api/v1/maps/library/{mid}/points", json={"name": "P1", "x": 1.0, "y": 1.0})
    p2 = auth_client.post(f"/api/v1/maps/library/{mid}/points", json={"name": "P2", "x": 2.0, "y": 2.0})
    assert p1.status_code == 200 and p2.status_code == 200

    tpl = auth_client.post("/api/v1/task-templates", json={
        "name": "测试模板", "map_id": mid,
        "actions": [{"point_id": p1.json()["id"], "action": "photo"},
                    {"point_id": p2.json()["id"], "action": "photo"}],
    })
    assert tpl.status_code == 200

    run = auth_client.post("/api/v1/task-runs", json={"template_id": tpl.json()["id"]})
    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "planned"
    assert body["progress"]["total"] == 2

    payload = {
        "external_id": "EXT-T-1", "name": "机器人任务", "status": "done",
        "steps": [
            {"seq": 1, "point_id": p1.json()["id"], "point_name": "P1", "action": "photo",
             "status": "ok", "result": {"photo": "/x.jpg"}},
            {"seq": 2, "point_id": p2.json()["id"], "point_name": "P2", "action": "photo",
             "status": "failed", "error": "云台超时"},
        ],
    }
    first = auth_client.post("/api/v1/task-runs/ingest", json=payload)
    assert first.status_code == 200
    assert first.json()["created"] is True
    assert first.json()["progress"] == {"total": 2, "ok": 1, "failed": 1}

    again = auth_client.post("/api/v1/task-runs/ingest", json=payload)
    assert again.json()["created"] is False
    listed = auth_client.get("/api/v1/task-runs").json()
    ids = [i["external_id"] for i in listed["items"] if i["external_id"] == "EXT-T-1"]
    assert len(ids) == 1                                # 幂等

    # 计划可以取消；已完成的不能
    assert auth_client.post(f"/api/v1/task-runs/{body['id']}/cancel").status_code == 200
    assert auth_client.post(f"/api/v1/task-runs/{first.json()['id']}/cancel").status_code == 400


def test_must_change_password_flow(auth_client):
    """初始密码必须改：新建/重置置 True，自己改完变 False。"""
    from fastapi.testclient import TestClient

    made = auth_client.post("/api/v1/users", json={
        "username": "pw_flow", "password": "Init12345", "role": "operator"})
    assert made.status_code == 200

    c = TestClient(auth_client.app)
    r = c.post("/api/v1/auth/login", json={"username": "pw_flow", "password": "Init12345"})
    assert r.status_code == 200
    assert r.json()["user"]["must_change_password"] is True
    c.headers.update({"X-CSRF-Token": r.json()["csrf_token"]})

    changed = c.post("/api/v1/auth/password",
                     json={"old_password": "Init12345", "new_password": "Changed12345"})
    assert changed.status_code == 200
    me = c.get("/api/v1/auth/me").json()
    assert me["must_change_password"] is False

    # 管理员重置密码后又要改
    uid = made.json()["id"]
    assert auth_client.post(f"/api/v1/users/{uid}/password",
                            json={"password": "Reset12345"}).status_code == 200
    assert auth_client.get("/api/v1/users").json()[-1] is not None
    rows = {u["username"]: u for u in auth_client.get("/api/v1/users").json()}
    assert rows["pw_flow"]["must_change_password"] is True


def test_inspection_flow(auth_client):
    """人工巡检：计划 → 生成任务 → 扫码错码被拒 → 正确打卡 → 全打完才能完成。"""
    plan = auth_client.post("/api/v1/inspection/plans", json={
        "name": "泵房巡检", "shift": "早班",
        "items": [{"name": "泵房A", "code": "P-001", "checks": ["外观", "渗漏"]},
                  {"name": "配电柜B", "code": "P-002", "checks": ["指示灯"]}],
    })
    assert plan.status_code == 200
    assert plan.json()["point_count"] == 2

    empty = auth_client.post("/api/v1/inspection/plans", json={"name": "x", "items": []})
    assert empty.status_code == 400

    task = auth_client.post("/api/v1/inspection/tasks/generate",
                            json={"plan_id": plan.json()["id"], "due_hours": 8})
    assert task.status_code == 200
    t = task.json()
    assert t["status"] == "pending" and t["progress"]["total"] == 2

    first, second = t["items"][0]["id"], t["items"][1]["id"]
    bad = auth_client.post(f"/api/v1/inspection/tasks/{t['id']}/items/{first}/check",
                           json={"result": "ok", "code": "WRONG"})
    assert bad.status_code == 400

    ok = auth_client.post(f"/api/v1/inspection/tasks/{t['id']}/items/{first}/check",
                          json={"result": "abnormal", "code": "P-001", "note": "渗漏"})
    assert ok.status_code == 200 and ok.json()["item"]["scanned"] is True

    assert auth_client.post(f"/api/v1/inspection/tasks/{t['id']}/finish").status_code == 400

    auth_client.post(f"/api/v1/inspection/tasks/{t['id']}/items/{second}/check",
                     json={"result": "ok", "code": "P-002"})
    done = auth_client.post(f"/api/v1/inspection/tasks/{t['id']}/finish")
    assert done.status_code == 200 and done.json()["status"] == "done"


def test_work_order_flow(auth_client):
    """工单：不能跳步、销号必须填结论；告警可转工单。"""
    made = auth_client.post("/api/v1/work-orders", json={
        "title": "泵体渗漏", "source": "manual", "level": "critical"})
    assert made.status_code == 200
    o = made.json()
    assert o["status"] == "open" and o["code"]

    assert auth_client.post(f"/api/v1/work-orders/{o['id']}/transition",
                            json={"status": "closed", "resolution": "x"}).status_code == 400
    assert auth_client.post(f"/api/v1/work-orders/{o['id']}/assign",
                            json={"assignee_id": 1, "due_hours": 4}).status_code == 200
    assert auth_client.post(f"/api/v1/work-orders/{o['id']}/transition",
                            json={"status": "processing"}).status_code == 200
    assert auth_client.post(f"/api/v1/work-orders/{o['id']}/transition",
                            json={"status": "review"}).status_code == 200
    assert auth_client.post(f"/api/v1/work-orders/{o['id']}/transition",
                            json={"status": "closed"}).status_code == 400
    closed = auth_client.post(f"/api/v1/work-orders/{o['id']}/transition",
                              json={"status": "closed", "resolution": "更换密封圈"})
    assert closed.status_code == 200 and closed.json()["status"] == "closed"


def test_api_key_and_ai_ingest(auth_client):
    """API Key 给机器用：不带 Cookie/CSRF 也能推任务结果和 AI 识别结果。"""
    import base64
    from fastapi.testclient import TestClient

    made = auth_client.post("/api/v1/api-clients", json={
        "name": "算法盒-01", "scopes": ["ai:write", "task:ingest"]})
    assert made.status_code == 200
    raw = made.json()["key"]
    assert raw.startswith("jck_")

    machine = TestClient(auth_client.app)          # 全新会话，没有任何 Cookie
    headers = {"X-Api-Key": raw}

    # 任务回传（幂等）
    payload = {"external_id": "EXT-KEY-1", "name": "机器人任务", "status": "done",
               "steps": [{"seq": 1, "point_name": "P1", "action": "photo", "status": "ok"}]}
    r1 = machine.post("/api/v1/task-runs/ingest", json=payload, headers=headers)
    assert r1.status_code == 200, r1.text
    assert r1.json()["created"] is True
    r2 = machine.post("/api/v1/task-runs/ingest", json=payload, headers=headers)
    assert r2.json()["created"] is False

    # 没签名的会话拿不到
    assert TestClient(auth_client.app).post(
        "/api/v1/task-runs/ingest", json=payload).status_code == 401

    # AI 结果：图 + 置信度 → 生成告警
    png = base64.b64encode(b"\xff\xd8\xff\xd9fakejpeg").decode()
    body = {"algorithm": "meter", "camera_id": 7, "value": 12.5, "confidence": 0.92,
            "text": "表计读数 12.5 MPa", "image_base64": png}
    res = machine.post("/api/v1/ai/results", json=body, headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["duplicated"] is False and data["alarm_id"]

    again = machine.post("/api/v1/ai/results", json={**body, "ts": data["ts"]}, headers=headers)
    assert again.json()["duplicated"] is True

    # 告警确实带上了 camera_id，能回看
    alarms = auth_client.get("/api/v1/alarms").json()["items"]
    hit = [a for a in alarms if a["metric"] == "ai_meter"]
    assert hit and hit[0]["camera_id"] == 7

    # 原图能取
    img = auth_client.get(f"/api/v1/ai/results/{data['id']}/image")
    assert img.status_code == 200 and img.content

    # 吊销后立刻失效
    auth_client.delete(f"/api/v1/api-clients/{made.json()['id']}")
    assert machine.post("/api/v1/ai/results", json=body, headers=headers).status_code == 401


def test_webhook_signature_and_retry(monkeypatch):
    """外发带 HMAC 签名；失败会落库并可重投。"""
    import hashlib
    import hmac
    import json as _json
    import types

    from app.services import notify as notify_svc

    captured = {}

    class FakeResp:
        status_code = 200
        text = "ok"

        def json(self):
            return {"errcode": 0}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, content=None, headers=None):
            captured["url"] = url
            captured["content"] = content
            captured["headers"] = headers
            return FakeResp()

    monkeypatch.setattr(notify_svc.httpx, "Client", FakeClient)

    channel = types.SimpleNamespace(id=1, name="测试通道", type="generic",
                                    config_json=_json.dumps({"url": "http://example/hook",
                                                             "secret": "s3cret"}))
    alarm = {"id": 9, "metric": "battery", "level": "warn", "message": "电量低"}
    ok, status = notify_svc.send_once(channel, alarm)
    assert ok

    h = captured["headers"]
    ts = h["X-Jcrob-Timestamp"]
    expect = hmac.new(b"s3cret", ts.encode() + b"." + captured["content"],
                      hashlib.sha256).hexdigest()
    assert h["X-Jcrob-Signature"] == f"sha256={expect}"
    assert _json.loads(captured["content"])["alarm"]["id"] == 9


def test_retry_once_resends_failed(auth_client):
    """失败的投递会被 retry_once 重新发出（模拟通道恢复）。"""
    from datetime import datetime, timedelta

    from app.db.session import SessionLocal
    from app.models.notify import NotifyChannel, NotifyLog
    from app.services.notify import NotifyDispatcher, send_once

    with SessionLocal() as db:
        ch = NotifyChannel(name="重试通道", type="generic",
                           config_json='{"url": "http://127.0.0.1:9/none"}', min_level="warn")
        db.add(ch)
        db.commit()
        db.refresh(ch)
        row = NotifyLog(ts=datetime.now() - timedelta(minutes=5), channel_id=ch.id,
                        channel_name=ch.name, alarm_id=None,
                        payload="x", ok=False, status="fail", error="fail",
                        payload_json='{"id": 1, "metric": "battery", "level": "warn", "message": "低电量"}',
                        attempts=1, next_retry_at=datetime.now() - timedelta(minutes=1))
        db.add(row)
        db.commit()
        cid, rid = ch.id, row.id

    called = {"n": 0}

    def fake_send(channel, alarm):
        called["n"] += 1
        return True, "ok"

    import app.services.notify as ns
    orig = ns.send_once
    ns.send_once = fake_send
    try:
        d = NotifyDispatcher(SessionLocal)
        n = d.retry_once()
    finally:
        ns.send_once = orig

    assert n == 1 and called["n"] == 1
    with SessionLocal() as db:
        got = db.get(NotifyLog, rid)
        assert got.ok is True and got.attempts == 2 and got.next_retry_at is None
        db.query(NotifyChannel).filter(NotifyChannel.id == cid).delete()
        db.query(NotifyLog).filter(NotifyLog.id == rid).delete()
        db.commit()


def test_password_history_and_audit(auth_client):
    """改密不能复用最近用过的密码；失败登录要进审计。"""
    from fastapi.testclient import TestClient

    r = auth_client.post("/api/v1/users", json={
        "username": "pw_hist", "password": "Init12345", "role": "viewer"})
    assert r.status_code == 200

    c = TestClient(auth_client.app)
    login = c.post("/api/v1/auth/login", json={"username": "pw_hist", "password": "Init12345"})
    c.headers.update({"X-CSRF-Token": login.json()["csrf_token"]})

    first = c.post("/api/v1/auth/password",
                   json={"old_password": "Init12345", "new_password": "Second12345"})
    assert first.status_code == 200

    # 复用刚用过的 Init12345 应被拒
    again = c.post("/api/v1/auth/password",
                   json={"old_password": "Second12345", "new_password": "Init12345"})
    assert again.status_code == 400
    assert again.json()["code"] == "PASSWORD_REUSED"

    # 失败登录写审计
    bad = TestClient(auth_client.app)
    bad.post("/api/v1/auth/login", json={"username": "pw_hist", "password": "nope-wrong"})
    logs = auth_client.get("/api/v1/audit-logs?limit=50").json()["items"]
    assert any(x["action"] == "auth.login_failed" for x in logs)


def test_audit_chain_detects_tamper(auth_client):
    """审计哈希链：正常通过；改一行内容/删一行都会被抓出来。"""
    from app.db.session import SessionLocal
    from app.models.operation_log import OperationLog

    # 产生几条真实审计
    auth_client.post("/api/v1/settings", json={"values": {"alarm.battery_warn": 19}})
    auth_client.post("/api/v1/settings", json={"values": {"alarm.battery_warn": 20}})

    ok = auth_client.get("/api/v1/audit-logs/verify").json()
    assert ok["ok"] is True and ok["checked"] >= 2

    with SessionLocal() as db:
        row = db.query(OperationLog).order_by(OperationLog.id.desc()).first()
        rid = row.id
        row.target = "被人改过了"
        db.commit()

    bad = auth_client.get("/api/v1/audit-logs/verify").json()
    assert bad["ok"] is False
    assert bad["broken_at"] == rid
    assert "row_hash" in bad["reason"]

    # 删中间一行：链断（prev_hash 对不上）
    with SessionLocal() as db:
        victim = db.query(OperationLog).order_by(OperationLog.id.desc()).offset(1).first()
        db.delete(victim)
        db.commit()
    again = auth_client.get("/api/v1/audit-logs/verify").json()
    assert again["ok"] is False


def test_totp_two_factor(auth_client):
    """开双因子：不带码不能登录；带对了才能进；密码正确也绕不过。"""
    from fastapi.testclient import TestClient

    from app.core.security import totp_code

    made = auth_client.post("/api/v1/users", json={
        "username": "totp_user", "password": "Init12345", "role": "viewer"})
    assert made.status_code == 200

    c = TestClient(auth_client.app)
    r = c.post("/api/v1/auth/login", json={"username": "totp_user", "password": "Init12345"})
    c.headers.update({"X-CSRF-Token": r.json()["csrf_token"]})
    # 先改初始密码，否则被强制改密拦住
    assert c.post("/api/v1/auth/password",
                  json={"old_password": "Init12345", "new_password": "Second12345"}).status_code == 200

    start = c.post("/api/v1/auth/totp/start")
    assert start.status_code == 200
    secret = start.json()["secret"]
    assert "otpauth://totp/" in start.json()["uri"]

    # 错误码启不了
    assert c.post("/api/v1/auth/totp/enable", json={"code": "000000"}).status_code == 400
    good = totp_code(secret)
    assert c.post("/api/v1/auth/totp/enable", json={"code": good}).status_code == 200

    fresh = TestClient(auth_client.app)
    # 只给密码 → 要求动态码
    need = fresh.post("/api/v1/auth/login",
                      json={"username": "totp_user", "password": "Second12345"})
    assert need.status_code == 401 and need.json()["code"] == "TOTP_REQUIRED"
    # 错码 → 拒绝
    wrong = fresh.post("/api/v1/auth/login", json={
        "username": "totp_user", "password": "Second12345", "totp_code": "000000"})
    assert wrong.status_code == 401 and wrong.json()["code"] == "TOTP_INVALID"
    # 对码 → 通过
    ok = fresh.post("/api/v1/auth/login", json={
        "username": "totp_user", "password": "Second12345", "totp_code": totp_code(secret)})
    assert ok.status_code == 200


def test_logout_revokes_and_role_gate(auth_client):
    """登出真的吊销旧 token；viewer 不能调机器回传接口。"""
    from fastapi.testclient import TestClient

    # 先建 viewer（登出会让 admin 的旧会话全部失效，所以顺序不能反）
    made = auth_client.post("/api/v1/users", json={
        "username": "gate_viewer", "password": "Init12345", "role": "viewer"})
    assert made.status_code == 200
    v = TestClient(auth_client.app)
    lr = v.post("/api/v1/auth/login", json={"username": "gate_viewer", "password": "Init12345"})
    assert lr.status_code == 200
    v.headers.update({"X-CSRF-Token": lr.json()["csrf_token"]})
    assert v.post("/api/v1/auth/password",
                  json={"old_password": "Init12345", "new_password": "Viewer12345"}).status_code == 200
    bad = v.post("/api/v1/task-runs/ingest", json={"external_id": "V-1", "steps": []})
    assert bad.status_code == 403

    # 单独开一个会话，拿到 token 原文
    c = TestClient(auth_client.app)
    r = c.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    token = r.cookies.get("jc_token")
    assert token
    assert c.get("/api/v1/auth/me").status_code == 200

    assert c.post("/api/v1/auth/logout",
                  headers={"X-CSRF-Token": r.json()["csrf_token"]}).status_code == 200

    replay = TestClient(auth_client.app)
    replay.cookies.set("jc_token", token)
    assert replay.get("/api/v1/auth/me").status_code == 401



def test_production_refuses_default_secret(monkeypatch):
    """prod 用默认密钥必须拒绝启动。"""
    from app.core.config import assert_production_safe, get_settings

    st = get_settings()
    monkeypatch.setattr(st, "env", "prod", raising=False)
    monkeypatch.setattr(st, "secret_key", "dev-only-secret-change-me-please-32b", raising=False)
    import pytest

    with pytest.raises(RuntimeError):
        assert_production_safe()


def test_dispatch_write_flow(auth_client):
    """写开关关着必须 403；开了之后 下发→暂停→继续→取消 全链路通。"""
    import io as _io
    from PIL import Image

    buf = _io.BytesIO()
    Image.new("RGB", (80, 80), "white").save(buf, format="PNG")
    m = auth_client.post("/api/v1/maps/library",
                         files={"file": ("d.png", buf.getvalue(), "image/png")},
                         data={"name": "下发测试图", "resolution": "0.05"})
    mid = m.json()["id"]
    pt = auth_client.post(f"/api/v1/maps/library/{mid}/points", json={"name": "P1", "x": 1, "y": 1})
    tpl = auth_client.post("/api/v1/task-templates", json={
        "name": "下发模板", "map_id": mid,
        "actions": [{"point_id": pt.json()["id"], "action": "photo"}]})
    run = auth_client.post("/api/v1/task-runs", json={"template_id": tpl.json()["id"]})
    rid = run.json()["id"]

    # 默认关闭
    locked = auth_client.post(f"/api/v1/task-runs/{rid}/dispatch")
    assert locked.status_code == 403
    assert locked.json()["code"] == "WRITE_LOCKED"

    # 打开写开关
    assert auth_client.put("/api/v1/settings", json={
        "values": {"robot.write_enabled": True}}).status_code == 200

    d = auth_client.post(f"/api/v1/task-runs/{rid}/dispatch")
    assert d.status_code == 200, d.text
    assert d.json()["status"] == "running"
    assert d.json()["external_id"]

    p = auth_client.post(f"/api/v1/task-runs/{rid}/pause")
    assert p.status_code == 200 and p.json()["paused"] is True

    r = auth_client.post(f"/api/v1/task-runs/{rid}/resume")
    assert r.status_code == 200 and r.json()["paused"] is False

    c = auth_client.post(f"/api/v1/task-runs/{rid}/cancel")
    assert c.status_code == 200 and c.json()["status"] == "cancelled"

    # 关回去，别影响其他用例
    auth_client.put("/api/v1/settings", json={"values": {"robot.write_enabled": False}})


def test_task_watchdog_raises_alarm(auth_client):
    """下发后长时间无进度 → 看门狗产生 critical 告警（不自动瞎停真机）。"""
    from datetime import datetime, timedelta

    from app.db.session import SessionLocal
    from app.models.task_run import TaskRun
    from app.services.task_dispatch import check_stuck

    with SessionLocal() as db:
        run = TaskRun(name="卡住的任务", status="running",
                      dispatched_at=datetime.now() - timedelta(minutes=5),
                      last_progress_at=datetime.now() - timedelta(minutes=5))
        db.add(run)
        db.commit()
        rid = run.id

    n = check_stuck(SessionLocal)
    assert n >= 1
    alarms = auth_client.get("/api/v1/alarms").json()["items"]
    assert any(a["metric"] == f"task_stuck_{rid}" for a in alarms)
    with SessionLocal() as db:
        db.query(TaskRun).filter(TaskRun.id == rid).delete()
        db.commit()


def test_modbus_gateway_end_to_end(auth_client, monkeypatch):
    """Modbus 网关：读模拟从站 → 入库 → 超限告警，一条链路走通。"""
    import socket
    import struct
    import threading

    from app.services.sensor_gateway import modbus_read, scale
    from app.services.sensor_io import ingest_value

    # 起一个极简 Modbus 从站：寄存器 0 = 85（×0.1 = 8.5 %LEL）
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def serve():
        conn, _ = srv.accept()
        with conn:
            head = conn.recv(7)
            tid, _proto, length, uid = struct.unpack(">HHHB", head)
            pdu = conn.recv(length - 1)
            func, _start, count = struct.unpack(">BHH", pdu[:5])
            payload = struct.pack(f">{count}H", *([85] * count))
            body = struct.pack(">BB", func, count * 2) + payload
            conn.sendall(struct.pack(">HHHB", tid, 0, len(body) + 1, uid) + body)

    threading.Thread(target=serve, daemon=True).start()

    regs = modbus_read("127.0.0.1", port, 1, 0, 1)
    assert regs == [85]
    assert scale(regs[0], {"scale": 0.1}) == 8.5
    srv.close()

    # 建传感器（阈值 5 %LEL）+ 网关，走服务层采集
    made = auth_client.post("/api/v1/sensors", json={
        "name": "可燃气体-模拟", "kind": "gas", "unit": "%LEL",
        "warn_high": 5, "crit_high": 10})
    assert made.status_code == 200
    sid = made.json()["id"]

    from app.db.session import SessionLocal
    from app.services import alarms as alarms_mod
    from app.models.alarm import AlarmRecord

    with SessionLocal() as db:
        res = ingest_value(db, sensor_id=sid, value=8.5, source="gateway")
    assert res["ok"] is True and res["level"] == "warn"

    # 网关 CRUD 配置校验
    bad = auth_client.post("/api/v1/sensor-gateways", json={
        "name": "缺映射", "protocol": "modbus", "host": "127.0.0.1", "port": 15020})
    assert bad.status_code == 400

    ok = auth_client.post("/api/v1/sensor-gateways", json={
        "name": "模拟网关", "protocol": "modbus", "host": "127.0.0.1", "port": 15020,
        "mapping": [{"sensor_id": sid, "register": 0, "scale": 0.1}]})
    assert ok.status_code == 200
    gid = ok.json()["id"]
    assert auth_client.get("/api/v1/sensor-gateways").json()[0]["protocol"] == "modbus"
    assert auth_client.delete(f"/api/v1/sensor-gateways/{gid}").status_code == 200
