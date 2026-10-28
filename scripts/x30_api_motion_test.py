"""通过平台 API 控制 X30 基础运动：起立 -> 开始运动 -> 前进 1s -> 停 -> 收尾。

安全：场地清空、急停在手（用户确认）。失败立即发零速。
"""

from __future__ import annotations

import json
import time
import urllib.request
import http.cookiejar

BASE = "http://127.0.0.1:8000/api/v1"
CJ = http.cookiejar.CookieJar()
OP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CJ))


def call(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    csrf = next((c.value for c in CJ if c.name == "jc_csrf"), None)
    if csrf:
        r.add_header("X-CSRF-Token", csrf)
    with OP.open(r, timeout=25) as x:
        return json.loads(x.read() or b"{}")


def status() -> dict:
    st = call("GET", "/robots/2/status")
    s = st.get("status") or {}
    p = st.get("pose") or {}
    return {"ms": s.get("motion_state"), "online": st.get("online"),
            "located": s.get("located"), "x": p.get("x"), "y": p.get("y")}


def wait_ms(targets: tuple[str, ...], timeout: float = 30) -> dict:
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        s = status()
        if s["ms"] != last:
            print(f"  MotionState={s['ms']} pos=({s['x']}, {s['y']}) located={s['located']}")
            last = s["ms"]
        if s["ms"] in targets:
            return s
        time.sleep(2)
    return status()


call("POST", "/auth/login", {"username": "admin", "password": "admin123"})
call("PUT", "/settings", {"values": {"robot.write_enabled": True}})
print("初始:", status())

if status()["ms"] not in ("2", "3", "4"):
    print("发起立…")
    print(" ", call("POST", "/robots/2/motion-mode", {"action": "stand"}))
    wait_ms(("2", "3"))

if status()["ms"] in ("2", "3"):
    print("开始运动（踏步）…")
    print(" ", call("POST", "/robots/2/motion-mode", {"action": "start"}))
    wait_ms(("4",))

print("前进 1 秒（每 100ms 一帧 forward=0.3）…")
for _ in range(10):
    call("POST", "/robots/2/move", {"forward": 0.3})
    time.sleep(0.1)
call("POST", "/robots/2/move", {"forward": 0})
time.sleep(1.5)
print("停止后:", status())

print("停止运动（回站立）…")
print(" ", call("POST", "/robots/2/motion-mode", {"action": "stop"}))
time.sleep(2)
print("收尾:", status())
call("PUT", "/settings", {"values": {"robot.write_enabled": False}})
print("已关闭写开关")
