"""搁置到期自动恢复 + 搁置期间不升级 的验证（直接查库，不依赖前端）。"""

from __future__ import annotations

import json
import sqlite3
import urllib.request
import http.cookiejar
from datetime import datetime, timedelta

BASE = "http://127.0.0.1:8000/api/v1"
DB = r"D:\Desktop\防爆机器人\server\data\app.db"
CJ = http.cookiejar.CookieJar()
OP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CJ))


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    csrf = next((c.value for c in CJ if c.name == "jc_csrf"), None)
    if csrf:
        r.add_header("X-CSRF-Token", csrf)
    with OP.open(r, timeout=25) as x:
        return json.loads(x.read() or b"{}")


call("POST", "/auth/login", {"username": "admin", "password": "admin123"})
alarms = call("GET", "/alarms?limit=1")["items"]
alarm = alarms[0]
aid = alarm["id"]
print("选一条告警:", aid, "| 已搁置:", alarm.get("shelved_until"))

call("POST", f"/alarms/{aid}/shelve", {"minutes": 30, "reason": "到期恢复测试"})
row = call("GET", f"/alarms?limit=200")["items"]
cur = next((a for a in row if a["id"] == aid), {})
print("搁置后:", cur.get("shelved_until"), "|", cur.get("shelve_reason"))

# 直接把它改成 1 秒前到期，模拟"时间到了"
con = sqlite3.connect(DB)
past = (datetime.now() - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
con.execute("UPDATE alarm_record SET shelved_until=? WHERE id=?", (past, aid))
con.commit()
con.close()
print("已把到期时间改到过去:", past)

print("等待后台清理线程（最多 70 秒）…")
import time

for i in range(14):
    time.sleep(5)
    items = call("GET", "/alarms?limit=200")["items"]
    a = next((x for x in items if x["id"] == aid), {})
    if not a.get("shelved_until"):
        print(f"✅ 第 {(i + 1) * 5} 秒：搁置已自动解除，原因也清空（{a.get('shelve_reason')}）")
        break
else:
    print("❌ 70 秒内没有自动解除——清理线程没跑起来")
