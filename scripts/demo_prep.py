"""演示前 1 分钟准备：开写开关、检查服务、造一条可讲的告警、打印检查清单。

用法：python scripts/demo_prep.py [--server http://127.0.0.1:8000]
不传 --server 时默认本地；客户现场改成 http://192.168.8.40:8099。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import http.cookiejar


def make_client(server: str):
    base = server.rstrip("/") + "/api/v1"
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def call(method: str, path: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        csrf = next((c.value for c in jar if c.name == "jc_csrf"), None)
        if csrf:
            req.add_header("X-CSRF-Token", csrf)
        try:
            with opener.open(req, timeout=30) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except Exception:  # noqa: BLE001
                return e.code, {"raw": raw[:120].decode("utf-8", "replace")}

    return call


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="admin123")
    args = ap.parse_args()
    call = make_client(args.server)

    st, _ = call("POST", "/auth/login", {"username": args.user, "password": args.password})
    if st != 200:
        print("登录失败，检查账号或服务", st)
        return 1
    print("1) 登录成功")

    st, _ = call("PUT", "/settings", {"values": {"robot.write_enabled": True}})
    print("2) 写开关：", "已开启" if st == 200 else f"失败 {st}")

    st, check = call("GET", "/system/self-check")
    if st == 200:
        bad = [c for c in check.get("checks", []) if not c.get("ok")]
        print(f"3) 自检：{len(check.get('checks', [])) - len(bad)} 项通过，{len(bad)} 项异常")
        for c in bad:
            print("   -", c["name"], "|", c["detail"], "|", (c.get("hint") or "")[:40])
    else:
        print("3) 自检接口不可用", st)

    # 造一条演示告警（重复跑会复用同名传感器，不会无限堆）
    st, sensors = call("GET", "/sensors")
    rows = sensors.get("items") if isinstance(sensors, dict) else sensors
    sid = None
    for s in rows or []:
        if s.get("name") == "演示-可燃气体":
            sid = s["id"]
            break
    if sid is None:
        st, s = call("POST", "/sensors", {"name": "演示-可燃气体", "kind": "gas",
                                         "robot_id": 1, "warn_high": 10, "crit_high": 20})
        sid = s.get("id") if isinstance(s, dict) else None
    if sid:
        call("POST", f"/sensors/{sid}/readings", {"value": 99, "source": "manual"})
        st, alarms = call("GET", "/alarms?limit=20")
        items = alarms.get("items") or []
        mine = [a for a in items if a.get("metric", "").startswith("演示") or
                "演示" in (a.get("message") or "")]
        print("4) 演示告警：", f"已生成 #{mine[0]['id']}（3D 里应出现红色光柱）" if mine
              else "已推读数，若没出告警请手动确认阈值")
    else:
        print("4) 演示告警：传感器创建失败，跳过（可用手动读数代替）")

    print("\n演示检查清单：")
    print(f"  · 打开 {args.server}/ 或前端地址，账号 {args.user}")
    print("  · 首页：四块面板有数、没有定位红条")
    print("  · 三维孪生（/twin）：机器人橙色标记、点位标签、墙体")
    print("  · 点一次「起立/趴下」或让车动 → 3D 里机器人应同步移动")
    print("  · 轨迹回放：选 24h → 播放 → 时间前进")
    print("  · 关「光效」对比帧率；关「高度分层」对比墙高")
    print("\n演示完记得：把写开关关掉（系统设置 → 下发开关）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
