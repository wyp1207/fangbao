"""验证本轮 P0/P1 修复：自动建单、环形图口径、改地址清流名、主设备探测、SLA 分母。"""

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
    with OP.open(r, timeout=30) as x:
        return json.loads(x.read() or b"{}")


call("POST", "/auth/login", {"username": "admin", "password": "admin123"})

# 1) 自动建单：造一条 critical 遥测告警，看是否生成工单
print("== 1. 严重告警自动建单 ==")
before = len(call("GET", "/work-orders?limit=1").get("items", []))
sensor = call("POST", "/sensors", {"name": "自动建单验证", "kind": "gas",
                                   "warn_high": 5, "crit_high": 10, "robot_id": 1})
sid = sensor["id"] if sensor.get("id") else None
# 用外设规则把阈值压低，再推一个越界值
call("POST", f"/sensors/{sid}/readings", {"value": 99, "source": "manual"})
alarms = call("GET", "/alarms?limit=3")["items"]
latest = alarms[0]
print("  最新告警:", latest["id"], latest["level"], "| priority:", latest.get("priority"))
orders = call("GET", "/work-orders?limit=50")["items"]
linked = [o for o in orders if o.get("source") == "alarm" and o.get("source_id") == latest["id"]]
print("  自动建单:", "✅ 工单 " + str(linked[0]["id"]) if linked else "❌ 没有工单")
if sid:
    try:
        call("DELETE", f"/sensors/{sid}")
        print("  已清理测试传感器", sid)
    except Exception as exc:  # noqa: BLE001
        print("  清理失败:", exc)

# 2) 环形图口径
print("\n== 2. 环形图口径 ==")
stats = call("GET", "/alarms/stats?days=7")
page_list = call("GET", "/alarms?limit=200")
print(f"  stats: total={stats['total']} unacked={stats['unacked']} acked={stats['acked']}")
print(f"  列表接口 limit=200 拿到 {len(page_list['items'])} 条 → 页面应显示 stats 的数（{stats['total']}）")

# 3) 改地址清流名
print("\n== 3. 改地址后清掉 stream_name ==")
vid = call("GET", "/videos?robot_id=1")[0]
print("  改前:", vid["id"], "stream=", vid["stream_name"], "url=", vid["url"][:40])
after = call("PATCH", f"/videos/{vid['id']}", {"url": "rtsp://admin:x@127.0.0.1:1/test"})
print("  改后:", "stream=", repr(after["stream_name"]), "（应为空）", "✅" if not after["stream_name"] else "❌")
# 还原
call("PATCH", f"/videos/{vid['id']}", {"url": vid["url"], "stream_name": vid["stream_name"]})

# 4) 主设备探测
print("\n== 4. 设备 1 读一次状态 ==")
probe = call("POST", "/devices/1/status-probe")
d = probe.get("data") or {}
print("  source:", probe.get("source"), "| online:", d.get("online"), "| age:", d.get("age_s"))
print("  判定:", "✅ 有真实数据" if d.get("online") else "❌ 仍是空壳")

# 5) SLA 分母
print("\n== 5. SLA 按期率口径 ==")
rm = call("GET", "/reports/summary")["response_metrics"]
print(f"  sla_on_time={rm['sla_on_time']} / sla_closed={rm['sla_closed']} = {rm['sla_on_time_rate']}%")
print("  说明：分母只算有 due_at 的工单（早期工单没有时限，不该算未按期）")
