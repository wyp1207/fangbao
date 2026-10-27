"""验证：审计缺口补齐 + P4 可达 + 优先级规则。"""

from __future__ import annotations

import json
import sqlite3
import urllib.request
import http.cookiejar

from app.services.alarms import priority_for

BASE = "http://127.0.0.1:8000/api/v1"
DB = r"D:\Desktop\防爆机器人\server\data\app.db"

print("== 1. 优先级规则 ==")
cases = [
    ("env_gas_1_critical", "critical", "P1"),
    ("battery", "critical", "P2"),
    ("battery", "warn", "P3"),
    ("offline", "warn", "P3"),
    ("disk", "critical", "P4"),
    ("clock_skew", "warn", "P4"),
    ("notify_failed", "critical", "P4"),
]
for metric, level, want in cases:
    got = priority_for(metric, level)
    print(f"  {metric:<22}{level:<10} → {got} {'✅' if got == want else '❌ 期望 ' + want}")

CJ = http.cookiejar.CookieJar()
OP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CJ))


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    csrf = next((c.value for c in CJ if c.name == "jc_csrf"), None)
    if csrf:
        r.add_header("X-CSRF-Token", csrf)
    with OP.open(r, timeout=30) as x:
        return json.loads(x.read() or b"{}")


call("POST", "/auth/login", {"username": "admin", "password": "admin123"})

print("\n== 2. 关闭告警 → 工单联动关闭是否留审计 ==")
alarm = call("GET", "/alarms?limit=200")["items"]
target = next((a for a in alarm if a.get("work_order_id") and not a.get("closed_at")), None)
if not target:
    print("  没有可用的『未关闭且有工单』告警，跳过")
else:
    aid, oid = target["id"], target["work_order_id"]
    before = sqlite3.connect(DB).execute(
        "SELECT count(*) FROM operation_log WHERE action='work_order.auto_close'").fetchone()[0]
    call("POST", f"/alarms/{aid}/close", {"resolution": "handled", "note": "联动关单审计验证"})
    con = sqlite3.connect(DB)
    after = con.execute(
        "SELECT count(*) FROM operation_log WHERE action='work_order.auto_close'").fetchone()[0]
    row = con.execute(
        "SELECT target, params_json FROM operation_log WHERE action='work_order.auto_close' "
        "ORDER BY id DESC LIMIT 1").fetchone()
    con.close()
    print(f"  告警 {aid} → 工单 {oid}；审计条数 {before} → {after}",
          "✅" if after > before else "❌")
    if row:
        print("  最新审计:", row[0], "|", (row[1] or "")[:80])

print("\n== 3. 搁置到期解除是否留审计 ==")
con = sqlite3.connect(DB)
before = con.execute("SELECT count(*) FROM operation_log WHERE action='alarm.unshelve_auto'").fetchone()[0]
alarm = call("GET", "/alarms?limit=200")["items"]
pick = next((a for a in alarm if not a.get("closed_at")), None)
if pick:
    call("POST", f"/alarms/{pick['id']}/shelve", {"minutes": 1, "reason": "自动解除审计验证"})
    con.execute("UPDATE alarm_record SET shelved_until=datetime('now','-1 minute') WHERE id=?",
                (pick["id"],))
    con.commit()
    con.close()
    print(f"  已把告警 {pick['id']} 的到期时间改到过去，等清理线程（≤70 秒）…")
    import time
    for i in range(14):
        time.sleep(5)
        con2 = sqlite3.connect(DB)
        after = con2.execute(
            "SELECT count(*) FROM operation_log WHERE action='alarm.unshelve_auto'").fetchone()[0]
        con2.close()
        if after > before:
            print(f"  ✅ 第 {(i + 1) * 5} 秒：新增审计 {before} → {after}")
            break
    else:
        print("  ❌ 70 秒内没看到 alarm.unshelve_auto 审计")
else:
    con.close()
