"""端到端验证 A（幂等）：清掉运行中的任务 → 建计划 → 连发两次。"""

from __future__ import annotations

import json
import urllib.request
import http.cookiejar

BASE = "http://127.0.0.1:8000/api/v1"
CJ = http.cookiejar.CookieJar()
OP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CJ))


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    csrf = next((c.value for c in CJ if c.name == "jc_csrf"), None)
    if csrf:
        r.add_header("X-CSRF-Token", csrf)
    try:
        with OP.open(r, timeout=30) as x:
            return x.status, json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:120]}


call("POST", "/auth/login", {"username": "admin", "password": "admin123"})
call("PUT", "/settings", {"values": {"robot.write_enabled": True}})

# 清掉设备 3 上还在跑的任务，否则会被 RUN_BUSY 挡住（另一条规则，属于正常保护）
runs = call("GET", "/task-runs?limit=100")[1].get("items", [])
for r in runs:
    if r.get("robot_id") == 3 and r.get("status") == "running":
        call("POST", "/task-runs/%s/cancel" % r["id"], {"reason": "验证前清理"})
        print("已取消运行中任务", r["id"])

tpls = call("GET", "/task-templates?limit=1")[1]
items = tpls.get("items") if isinstance(tpls, dict) else tpls
tid = items[0]["id"] if items else None
if not tid:
    print("没有模板，跳过")
    raise SystemExit(0)

st, run = call("POST", "/task-runs", {"name": "幂等验证", "robot_id": 3, "template_id": tid})
rid = run.get("id")
print("建任务:", st, rid, "| 点位:", (run.get("progress") or {}).get("total"))

s1, b1 = call("POST", "/task-runs/%s/dispatch" % rid)
print("第一次下发:", s1, b1.get("code") or b1.get("status") or str(b1)[:80])
s2, b2 = call("POST", "/task-runs/%s/dispatch" % rid)
print("第二次下发:", s2, b2.get("code") or str(b2)[:80])
print("判定:", "被拦住" if s2 in (400, 409) else "放行了")

info = call("GET", "/task-runs/%s" % rid)[1]
print("库内:", info.get("status"), "| order_id:", info.get("order_id"),
      "| dispatch_state:", info.get("dispatch_state"),
      "| attempt:", info.get("dispatch_attempt"))

call("PUT", "/settings", {"values": {"robot.write_enabled": False}})
print("已关闭写开关")
