"""端到端跑一条完整巡航（模拟器），验证：下发→逐点→到点→动作→done。"""

from __future__ import annotations

import json
import time
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
        with OP.open(r, timeout=40) as x:
            return x.status, json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:150].decode("utf-8", "replace")}


call("POST", "/auth/login", {"username": "admin", "password": "admin123"})
call("PUT", "/settings", {"values": {"robot.write_enabled": True}})

maps = call("GET", "/maps/library")[1]
rows = maps.get("items") if isinstance(maps, dict) else maps
map_id = rows[0]["id"]
print("地图:", map_id)
points = call("GET", "/maps/library/%s/points" % map_id)[1]
points = points.get("items") if isinstance(points, dict) else points
points = (points or [])[:3]
print("点位:", [(p["id"], p["name"], p.get("x"), p.get("y")) for p in points])

tpl = {
    "name": "巡航E2E-%d" % int(time.time()),
    "robot_id": 3,
    "actions": [{"point_id": p["id"], "action": "wait", "sec": 1} for p in points],
}
st, t = call("POST", "/task-templates", tpl)
if st not in (200, 201):
    print("建模板失败:", st, t)
    raise SystemExit(1)
print("模板:", t.get("id"))

st, run = call("POST", "/task-runs", {"name": "巡航E2E", "robot_id": 3, "template_id": t["id"]})
rid = run.get("id")
print("执行记录:", rid, "点位:", (run.get("progress") or {}).get("total"))

st, c = call("POST", "/task-runs/%s/cruise" % rid)
print("启动巡航:", st, c)

for i in range(30):
    time.sleep(2)
    st, info = call("GET", "/task-runs/%s" % rid)
    status = info.get("status")
    prog = info.get("progress") or {}
    if status in ("done", "failed", "cancelled"):
        print("最终:", status, "| 进度:", prog)
        for s in info.get("steps") or []:
            print("  ", s["seq"], s["point_name"], s["status"],
                  (s.get("error") or "")[:40], (s.get("result") or {}))
        break
else:
    st, info = call("GET", "/task-runs/%s" % rid)
    print("超时未结束:", info.get("status"), info.get("progress"))

call("PUT", "/settings", {"values": {"robot.write_enabled": False}})
print("已关闭写开关")
