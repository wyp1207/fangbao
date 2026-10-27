"""对抗测试：越权访问 + 审计链篡改检测（可直接跑）。"""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request
import http.cookiejar

BASE = "http://127.0.0.1:8000/api/v1"
DB = r"D:\Desktop\防爆机器人\server\data\app.db"


def client():
    cj = http.cookiejar.CookieJar()
    return cj, urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def call(op, cj, method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    csrf = next((c.value for c in cj if c.name == "jc_csrf"), None)
    if csrf:
        r.add_header("X-CSRF-Token", csrf)
    if token:
        r.add_header("X-API-Key", token)
    try:
        with op.open(r, timeout=20) as x:
            return x.status, json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:120]


def main() -> None:
    # 1) viewer 能不能干管理员的事
    cj, op = client()
    call(op, cj, "POST", "/auth/login", {"username": "admin", "password": "admin123"})
    st, users = call(op, cj, "GET", "/users")
    print("管理员看用户列表:", st)

    # 造一个 viewer 账号（已存在则忽略）
    st, _ = call(op, cj, "POST", "/users", {
        "username": "qa_viewer", "password": "Qa#123456", "role": "viewer", "name": "只读测试"})
    print("建 viewer:", st)

    cj2, op2 = client()
    st, res = call(op2, cj2, "POST", "/auth/login", {"username": "qa_viewer", "password": "Qa#123456"})
    print("viewer 登录:", st, res if st != 200 else "")

    checks = [
        ("POST", "/users", {"username": "x", "password": "Yy#123456", "role": "admin"}, "新建管理员"),
        ("POST", "/alarms/1/shelve", {"minutes": 5, "reason": "越权测试"}, "搁置告警"),
        ("DELETE", "/users/1", None, "删管理员"),
        ("PUT", "/settings", {"values": {"security.idle_minutes": 1}}, "改系统设置"),
        ("POST", "/task-runs/1/dispatch", {}, "下发任务"),
        ("GET", "/audit-logs/verify", None, "校验审计链"),
    ]
    print("\n== viewer 越权探测（期望除读取外全部 401/403）==")
    for method, path, body, label in checks:
        st, _ = call(op2, cj2, method, path, body)
        verdict = "✅ 拦住了" if st in (401, 403) else f"❌ 放行了（{st}）"
        print(f"  {label:<12} {method} {path:<28} → {st} {verdict}")

    # 2) 审计链篡改检测：改一条记录的 summary 再校验
    print("\n== 审计链篡改检测 ==")
    con = sqlite3.connect(DB)
    row = con.execute("SELECT id, result_summary FROM operation_log ORDER BY id DESC LIMIT 1").fetchone()
    if row:
        oid, old = row
        con.execute("UPDATE operation_log SET result_summary='tampered-for-test' WHERE id=?", (oid,))
        con.commit()
        st, res = call(op, cj, "GET", "/audit-logs/verify")
        print(f"  篡改 #{oid} 后校验: {st} → {json.dumps(res, ensure_ascii=False)[:140]}")
        con.execute("UPDATE operation_log SET result_summary=? WHERE id=?", (old, oid))
        con.commit()
        st, res = call(op, cj, "GET", "/audit-logs/verify")
        print(f"  恢复后校验: {st} → {json.dumps(res, ensure_ascii=False)[:140]}")
    con.close()


if __name__ == "__main__":
    main()
