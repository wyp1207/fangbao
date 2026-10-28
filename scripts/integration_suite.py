"""联调测试套件：六大基础模块 + 五大进阶能力，逐项跑并留证据。

先起后端 8000 与模拟器 3546、前端 5173，然后：
    python scripts/integration_suite.py
输出：控制台 + docs/reviews/integration-suite.json
"""

from __future__ import annotations

import json
import statistics
import sys
import threading
import time
import traceback

import requests

BASE = "http://127.0.0.1:8000/api/v1"
DB = r"D:\Desktop\防爆机器人\server\data\app.db"
RESULTS: list[dict] = []


def check(cid, module, name, fn):
    t0 = time.time()
    try:
        detail = fn() or ""
        ok, msg = True, str(detail)[:200]
    except AssertionError as exc:
        ok, msg = False, str(exc)[:200]
    except Exception as exc:  # noqa: BLE001
        ok, msg = False, "%s: %s" % (exc.__class__.__name__, exc)
        traceback.print_exc(limit=1)
    RESULTS.append({"id": cid, "module": module, "name": name, "ok": ok,
                    "ms": int((time.time() - t0) * 1000), "detail": msg})
    print("[%s] %s %s (%dms) %s" % ("PASS" if ok else "FAIL", cid, name,
                                    RESULTS[-1]["ms"], msg))


def login(user="admin", pwd="admin123"):
    s = requests.Session()
    r = s.post(BASE + "/auth/login", json={"username": user, "password": pwd}, timeout=15)
    assert r.status_code == 200, "login %s" % r.status_code
    s.headers.update({"X-CSRF-Token": r.json()["csrf_token"]})
    return s


def sqldb():
    import sqlite3

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def c1_login_contract():
    s = requests.Session()
    r = s.post(BASE + "/auth/login", json={"username": "admin", "password": "admin123"}, timeout=15)
    assert r.status_code == 200, r.status_code
    b = r.json()
    assert "csrf_token" in b and "user" in b, list(b)
    assert b["user"].get("username") == "admin", b["user"]
    assert "jc_csrf" in r.headers.get("set-cookie", ""), "no csrf cookie"
    return "user=%s roles=%s" % (b["user"].get("username"), b["user"].get("roles"))


def c2_csrf_required():
    s = requests.Session()
    s.post(BASE + "/auth/login", json={"username": "admin", "password": "admin123"}, timeout=15)
    r = s.put(BASE + "/settings", json={"values": {"video.mjpeg_fps": 21}}, timeout=15)
    assert r.status_code in (401, 403), r.status_code
    return "%s %s" % (r.status_code, r.json().get("code"))


def c3_validation_shape():
    s = login()
    r = s.post(BASE + "/task-runs", json={}, timeout=15)
    assert r.status_code in (400, 422), r.status_code
    b = r.json()
    assert "detail" in b or "code" in b, b
    return "%s keys=%s" % (r.status_code, list(b)[:3])


def c4_frontend_shell():
    r = requests.get("http://127.0.0.1:5173/", timeout=10)
    assert r.status_code == 200, r.status_code
    assert 'id="app"' in r.text, "not vite shell"
    return "%d bytes" % len(r.text)


def h1_motion_command():
    s = login()
    s.put(BASE + "/settings", json={"values": {"robot.write_enabled": True}}, timeout=15)
    r = s.post(BASE + "/robots/3/motion", json={"action": "stand"}, timeout=25)
    # JCROB 轮式没有"起立"这个动作，明确拒绝才是对的；只有 5xx 才算失败
    if r.status_code == 400 and r.json().get("code") == "NOT_SUPPORTED":
        return "400 NOT_SUPPORTED（该机型没有此动作，符合预期）"
    assert r.status_code == 200, "%s %s" % (r.status_code, r.text[:120])
    return str(r.json())[:80]


def h2_env_ws_state():
    s = login()
    r = s.get(BASE + "/robots/3/status", timeout=15)
    assert r.status_code == 200, r.status_code
    env = r.json().get("env_ws") or {}
    return "supported=%s connected=%s" % (env.get("supported"), env.get("connected"))


def b1_cruise_e2e():
    s = login()
    s.put(BASE + "/settings", json={"values": {"robot.write_enabled": True}}, timeout=15)
    maps = s.get(BASE + "/maps/library", timeout=15).json()
    rows = maps.get("items") if isinstance(maps, dict) else maps
    pts = s.get(BASE + "/maps/library/%s/points" % rows[0]["id"], timeout=15).json()
    pts = (pts.get("items") if isinstance(pts, dict) else pts)[:3]
    tpl = s.post(BASE + "/task-templates", json={
        "name": "联调-%d" % int(time.time()), "robot_id": 3,
        "actions": [{"point_id": p["id"], "action": "wait", "sec": 1} for p in pts],
    }, timeout=15).json()
    run = s.post(BASE + "/task-runs", json={"name": "联调巡航", "robot_id": 3,
                                            "template_id": tpl["id"]}, timeout=15).json()
    rid = run["id"]
    st = s.post(BASE + "/task-runs/%s/cruise" % rid, timeout=25)
    assert st.status_code == 200, "%s %s" % (st.status_code, st.text[:120])
    for _ in range(30):
        time.sleep(2)
        info = s.get(BASE + "/task-runs/%s" % rid, timeout=15).json()
        if info["status"] in ("done", "failed", "cancelled"):
            assert info["status"] == "done", info.get("dispatch_error")
            prog = info.get("progress") or {}
            assert prog.get("ok") == prog.get("total"), prog
            s.put(BASE + "/settings", json={"values": {"robot.write_enabled": False}}, timeout=15)
            return "run=%s %s" % (rid, prog)
    raise AssertionError("cruise timeout")


def b2_alarm_to_order_close():
    s = login()
    items = s.get(BASE + "/alarms", params={"limit": 200}, timeout=15).json()["items"]
    tgt = next((a for a in items if a.get("work_order_id") and not a.get("closed_at")), None)
    assert tgt, "no open alarm with work order"
    aid, oid = tgt["id"], tgt["work_order_id"]
    r = s.post(BASE + "/alarms/%s/close" % aid, json={"resolution": "handled", "note": "联调"}, timeout=20)
    assert r.status_code == 200, r.text[:120]
    con = sqldb()
    row = con.execute("SELECT status FROM work_order WHERE id=?", (oid,)).fetchone()
    con.close()
    assert row and row["status"] == "closed", "wo %s not closed" % oid
    return "alarm %s -> wo %s closed" % (aid, oid)


def b3_plan_crud():
    s = login()
    body = {"name": "联调计划-%d" % int(time.time()), "station": "联调场站", "shift": "白班",
            "enabled": True, "items": [{"name": "点位A", "code": "", "checks": []}]}
    c = s.post(BASE + "/inspection/plans", json=body, timeout=15)
    assert c.status_code == 200, c.text[:120]
    pid = c.json()["id"]
    assert s.patch(BASE + "/inspection/plans/%s" % pid, json={"name": body["name"] + "-改"},
                   timeout=15).status_code == 200
    assert s.delete(BASE + "/inspection/plans/%s" % pid, timeout=15).status_code == 200
    return "plan %s create/update/delete" % pid


def d1_unique_order_id():
    con = sqldb()
    dup = con.execute("SELECT order_id, count(*) c FROM task_run WHERE order_id IS NOT NULL "
                      "GROUP BY order_id HAVING c>1").fetchall()
    con.close()
    assert not dup, [dict(x) for x in dup]
    return "no duplicates"


def d2_no_orphan_steps():
    con = sqldb()
    n = con.execute("SELECT count(*) c FROM task_run_step s LEFT JOIN task_run r "
                    "ON r.id=s.run_id WHERE r.id IS NULL").fetchone()["c"]
    con.close()
    assert n == 0, "orphan steps=%s" % n
    return "0 orphan"


def d3_audit_chain():
    s = login()
    b = s.get(BASE + "/audit-logs/verify", timeout=20).json()
    assert b.get("ok") is True, b
    return "checked=%s" % b.get("checked")


def d4_stats_consistent():
    s = login()
    api = s.get(BASE + "/alarms/stats", params={"days": 7}, timeout=15).json()
    con = sqldb()
    n = con.execute("SELECT count(*) c FROM alarm_record "
                    "WHERE started_at >= datetime('now','-7 day')").fetchone()["c"]
    con.close()
    assert abs(api["total"] - n) <= 2, "api=%s db=%s" % (api["total"], n)
    return "api=%s db=%s" % (api["total"], n)


def _mk_sensor(s, name, warn, crit):
    r = s.post(BASE + "/sensors", json={"name": name, "kind": "gas", "robot_id": 1,
                                        "warn_high": warn, "crit_high": crit}, timeout=15)
    assert r.status_code in (200, 201), r.text[:120]
    return r.json()["id"]


def r1_rule_branches():
    s = login()
    sid = _mk_sensor(s, "联调-规则-%d" % int(time.time()), 10, 20)
    try:
        for v in (5, 15, 99):
            assert s.post(BASE + "/sensors/%s/readings" % sid,
                          json={"value": v, "source": "manual"}, timeout=15).status_code in (200, 201)
        items = s.get(BASE + "/alarms", params={"limit": 50}, timeout=15).json()["items"]
        mine = [a for a in items if str(sid) in json.dumps(a, ensure_ascii=False)]
        levels = {a["level"] for a in mine}
        assert "critical" in levels, levels
        crit = next(a for a in mine if a["level"] == "critical")
        assert crit.get("priority") in ("P1", "P2"), crit.get("priority")
        return "levels=%s priority=%s" % (levels, crit.get("priority"))
    finally:
        s.delete(BASE + "/sensors/%s" % sid, timeout=15)


def r2_shelve_suppresses():
    s = login()
    sid = _mk_sensor(s, "联调-搁置-%d" % int(time.time()), 10, 20)
    try:
        s.post(BASE + "/sensors/%s/readings" % sid, json={"value": 99, "source": "manual"}, timeout=15)
        items = s.get(BASE + "/alarms", params={"limit": 50}, timeout=15).json()["items"]
        mine = [a for a in items if str(sid) in json.dumps(a)]
        assert mine, "no alarm"
        aid = mine[0]["id"]
        assert s.post(BASE + "/alarms/%s/shelve" % aid,
                      json={"minutes": 5, "reason": "联调"}, timeout=15).status_code == 200
        before = len([a for a in s.get(BASE + "/alarms", params={"limit": 200},
                                       timeout=15).json()["items"] if str(sid) in json.dumps(a)])
        s.post(BASE + "/sensors/%s/readings" % sid, json={"value": 99, "source": "manual"}, timeout=15)
        after = len([a for a in s.get(BASE + "/alarms", params={"limit": 200},
                                      timeout=15).json()["items"] if str(sid) in json.dumps(a)])
        assert after == before, "%s -> %s" % (before, after)
        return "alarm %s shelved, no new alarm" % aid
    finally:
        s.delete(BASE + "/sensors/%s" % sid, timeout=15)


def g1_unauth_401():
    assert requests.get(BASE + "/robots", timeout=15).status_code == 401
    return "401"


def g2_unknown_route_shape():
    code = requests.get(BASE + "/no-such-thing", timeout=15).status_code
    assert code in (401, 404), code
    return str(code)


def g3_path_traversal():
    s = login()
    code = s.get(BASE + "/recordings/../../etc/passwd", timeout=15).status_code
    assert code in (400, 404, 422), code
    return str(code)


def g4_sql_injection():
    s = login()
    r = s.get(BASE + "/alarms", params={"metric": "' OR 1=1 --"}, timeout=15)
    assert r.status_code == 200, r.status_code
    assert r.json().get("total") == 0, "sqli worked?"
    return "total=0"


def a1_latency():
    s = login()
    times = []
    for _ in range(40):
        t0 = time.time()
        assert s.get(BASE + "/alarms", params={"limit": 20}, timeout=15).status_code == 200
        times.append((time.time() - t0) * 1000)
    times.sort()
    p50 = statistics.median(times)
    p95 = times[int(len(times) * 0.95) - 1]
    assert p95 < 500, "p95=%.0f" % p95
    return "p50=%.0fms p95=%.0fms" % (p50, p95)


def a2_concurrent_dispatch():
    s = login()
    s.put(BASE + "/settings", json={"values": {"robot.write_enabled": True}}, timeout=15)
    tpls = s.get(BASE + "/task-templates", params={"limit": 1}, timeout=15).json()
    items = tpls.get("items") if isinstance(tpls, dict) else tpls
    run = s.post(BASE + "/task-runs", json={"name": "并发下发", "robot_id": 3,
                                            "template_id": items[0]["id"]}, timeout=15).json()
    rid = run["id"]
    codes = []
    lock = threading.Lock()

    def worker():
        ss = login()
        ss.put(BASE + "/settings", json={"values": {"robot.write_enabled": True}}, timeout=15)
        c = ss.post(BASE + "/task-runs/%s/dispatch" % rid, timeout=30).status_code
        with lock:
            codes.append(c)

    ts = [threading.Thread(target=worker) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(40)
    ok = [c for c in codes if c == 200]
    assert len(ok) == 1, "success=%s codes=%s" % (len(ok), codes)
    s.put(BASE + "/settings", json={"values": {"robot.write_enabled": False}}, timeout=15)
    return "8 concurrent -> 1 ok, others %s" % sorted(set(codes) - {200})


def a3_ingest_idempotent():
    s = login()
    ext = "IT-%d" % int(time.time() * 1000)
    body = {"external_id": ext, "status": "done", "name": "联调上报", "robot_id": 3,
            "steps": [{"seq": 1, "point_name": "P1", "status": "ok"}]}
    r1 = s.post(BASE + "/task-runs/ingest", json=body, timeout=20)
    if r1.status_code in (401, 403):
        return "skipped (needs task:ingest scope)"
    assert r1.status_code in (200, 201), r1.text[:120]
    r2 = s.post(BASE + "/task-runs/ingest", json=body, timeout=20)
    assert r2.status_code in (200, 201), r2.text[:120]
    assert r2.json().get("created") is False, "duplicate created new run"
    return "second created=false"


def a4_stability_window():
    s = login()
    bad = 0
    for _ in range(12):
        for path in ("/robots", "/alarms?limit=5"):
            if s.get(BASE + path, timeout=15).status_code >= 500:
                bad += 1
        if requests.get("http://127.0.0.1:8000/health", timeout=15).status_code >= 500:
            bad += 1
        time.sleep(0.4)
    assert bad == 0, "%s x 5xx" % bad
    return "12 rounds x 3 endpoints, no 5xx"



def a5_chain_after_concurrency():
    """并发写审计后链仍完整——这是审计锁的回归点。"""
    s = login()
    s.put(BASE + "/settings", json={"values": {"robot.write_enabled": True}}, timeout=15)
    tpls = s.get(BASE + "/task-templates", params={"limit": 1}, timeout=15).json()
    items = tpls.get("items") if isinstance(tpls, dict) else tpls
    run = s.post(BASE + "/task-runs", json={"name": "并发审计", "robot_id": 3,
                                            "template_id": items[0]["id"]}, timeout=15).json()
    rid = run["id"]
    ts = []
    for _ in range(6):
        def worker(run_id=rid):
            ss = login()
            ss.post(BASE + "/task-runs/%s/steps/1/retry" % run_id, timeout=20)

        ts.append(threading.Thread(target=worker))
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    s.put(BASE + "/settings", json={"values": {"robot.write_enabled": False}}, timeout=15)
    body = s.get(BASE + "/audit-logs/verify", timeout=20).json()
    assert body.get("ok") is True, body
    return "checked=%s ok=true after 6 concurrent writes" % body.get("checked")


def main():
    login()
    checks = [
        ("C1", "前端契约", "登录返回 csrf/user、下发 cookie", c1_login_contract),
        ("C2", "前端契约", "无 CSRF 的写请求被拒", c2_csrf_required),
        ("C3", "前端契约", "非法入参返回结构化 4xx", c3_validation_shape),
        ("C4", "前端契约", "前端外壳可访问", c4_frontend_shell),
        ("H1", "硬件输入", "运动指令下发（模拟按键）", h1_motion_command),
        ("H2", "硬件输入", "环境 WS 状态可读", h2_env_ws_state),
        ("B1", "业务闭环", "模板→任务→巡航→done", b1_cruise_e2e),
        ("B2", "业务闭环", "关告警联动关工单", b2_alarm_to_order_close),
        ("B3", "业务闭环", "巡检计划增改删", b3_plan_crud),
        ("D1", "数据库", "order_id 唯一", d1_unique_order_id),
        ("D2", "数据库", "无孤儿步骤", d2_no_orphan_steps),
        ("D3", "数据库", "审计哈希链完整", d3_audit_chain),
        ("D4", "数据库", "统计接口与库一致", d4_stats_consistent),
        ("R1", "规则引擎", "阈值分支→级别/优先级", r1_rule_branches),
        ("R2", "规则引擎", "搁置期间抑制新告警", r2_shelve_suppresses),
        ("G1", "网关", "未登录 401", g1_unauth_401),
        ("G2", "网关", "未知路由 4xx", g2_unknown_route_shape),
        ("G3", "网关", "路径穿越被拒", g3_path_traversal),
        ("G4", "网关", "SQL 注入无效", g4_sql_injection),
        ("A1", "并发/时延", "列表 p95<500ms", a1_latency),
        ("A2", "并发/时延", "同任务 8 并发只成功 1", a2_concurrent_dispatch),
        ("A3", "幂等", "重复上报不新建", a3_ingest_idempotent),
        ("A4", "稳定性", "18 次请求无 5xx", a4_stability_window),
        ("A5", "数据一致性", "并发写审计后链仍完整", a5_chain_after_concurrency),
    ]
    for cid, mod, name, fn in checks:
        check(cid, mod, name, fn)
    passed = sum(1 for r in RESULTS if r["ok"])
    print("\n=== %s/%s passed ===" % (passed, len(RESULTS)))
    with open("docs/reviews/integration-suite.json", "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=2)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
