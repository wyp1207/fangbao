"""联调预案演练：用平台自己的接口把《真机联调预案》的检查项跑一遍。

目的不是"证明系统好"，而是**证明预案能执行**：
哪些检查项现在就能自动跑、哪些必须真机、哪些步骤预案里想当然了。

用法：
    python tools_dryrun_plan.py --base http://127.0.0.1:8000 \
        --user admin --password admin123 --minutes 2

11-10 真机到场后，把 --base 指向真机接入后的平台、把 mode 改成 jcrob_http，
同一份脚本就是现场验收记录（输出 markdown 可直接贴进验收报告）。
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from datetime import datetime
from http.cookiejar import CookieJar

PASS, FAIL, MANUAL = "通过", "失败", "需真机/人工"


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = ""

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.base}/api/v1{path}", data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.csrf:
            req.add_header("X-CSRF-Token", self.csrf)
        try:
            with self.opener.open(req, timeout=15) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")[:300]

    def login(self, user: str, password: str) -> None:
        status, body = self.call("POST", "/auth/login", {"username": user, "password": password})
        if status != 200:
            raise SystemExit(f"登录失败：{status} {body}")
        self.csrf = body.get("csrf_token", "")


def check(name: str, ok: bool | None, detail: str, section: str) -> dict:
    return {"section": section, "name": name,
            "result": PASS if ok is True else FAIL if ok is False else MANUAL,
            "detail": detail}


def d1_readonly(c: Client) -> list[dict]:
    out: list[dict] = []
    status, health = c.call("GET", "/health/deep")
    snap = (health or {}).get("cache", {}) if isinstance(health, dict) else {}
    out.append(check("深探针可读", status == 200, f"HTTP {status}", "D1"))
    out.append(check("机器人链路在线", bool(snap.get("online")),
                     f"online={snap.get('online')} age={snap.get('age_s')}", "D1"))
    out.append(check("数据年龄 < 3s", (snap.get("age_s") or 99) < 3,
                     f"age_s={snap.get('age_s')}", "D1"))

    _, st = c.call("GET", "/robots/1/status")
    _, pose = c.call("GET", "/robots/1/pose")
    if isinstance(st, dict) and isinstance(pose, dict):
        same = (st.get("online") == pose.get("online"))
        out.append(check("status 与 pose 一致", same,
                         f"status.online={st.get('online')} pose.online={pose.get('online')}", "D1"))
        out.append(check("位姿字段齐全", bool(pose.get("pose")),
                         f"pose keys={list((pose.get('pose') or {}).keys())[:5]}", "D1"))

    _, maps = c.call("GET", "/robots/1/maps")
    out.append(check("地图列表可读", isinstance(maps, list) and len(maps) > 0,
                     f"{len(maps) if isinstance(maps, list) else 0} 张", "D1"))
    return out


def d2_soak(c: Client, minutes: int) -> list[dict]:
    ages: list[float] = []
    fails = 0
    t0 = time.time()
    while time.time() - t0 < minutes * 60:
        code, health = c.call("GET", "/health/deep")
        if code != 200 or not isinstance(health, dict):
            fails += 1
        else:
            ages.append(float(health.get("cache", {}).get("age_s") or 0))
        time.sleep(5)
    return [
        check("连续采样无失败", fails == 0, f"{fails} 次失败 / {len(ages)} 次成功", "D2"),
        check("数据年龄中位数 < 3s",
              bool(ages) and statistics.median(ages) < 3,
              f"median={round(statistics.median(ages), 2) if ages else 'n/a'}s", "D2"),
        check("断网 60s 只报 1 条 warn", None, "需要拔网线，mock 环境无法自动验证", "D2"),
    ]


def _upload_map(c: Client) -> bool:
    """没有平台地图时自建一张：演练脚本应当自给自足，不靠人手准备。"""
    import uuid

    try:
        from PIL import Image
    except ImportError:
        return False
    import os
    import tempfile

    png = os.path.join(tempfile.gettempdir(), f"dryrun-{uuid.uuid4().hex}.png")
    Image.new("RGB", (400, 300), "white").save(png, format="PNG")
    boundary = "----dryrun" + uuid.uuid4().hex
    fields = {"name": "演练地图", "resolution": "0.05"}
    body = b""
    for k, v in fields.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
             f"filename=\"dryrun.png\"\r\nContent-Type: image/png\r\n\r\n").encode()
    body += open(png, "rb").read() + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(f"{c.base}/api/v1/maps/library", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("X-CSRF-Token", c.csrf)
    try:
        with c.opener.open(req, timeout=20) as resp:
            ok = resp.status == 200
    except Exception:  # noqa: BLE001
        ok = False
    os.unlink(png)
    return ok


def _make_run(c: Client, point_count: int) -> dict | None:
    """建模板 + 生成计划，返回 run。没有地图/点位就自动补。"""
    code, libs = c.call("GET", "/maps/library")
    if code != 200 or not libs:
        if not _upload_map(c):
            return None
        code, libs = c.call("GET", "/maps/library")
        if code != 200 or not libs:
            return None
    mid = libs[0]["id"]
    _, pts = c.call("GET", f"/maps/library/{mid}/points")
    if not pts:
        # 没有点位就先建一个
        c.call("POST", f"/maps/library/{mid}/points", {"name": "演练点", "x": 1.0, "y": 1.0})
        _, pts = c.call("GET", f"/maps/library/{mid}/points")
    use = [p for p in pts][:point_count]
    _, tpl = c.call("POST", "/task-templates", {
        "name": f"演练-{datetime.now().strftime('%H%M%S')}", "map_id": mid,
        "actions": [{"point_id": p["id"], "action": "photo"} for p in use]})
    if not isinstance(tpl, dict) or "id" not in tpl:
        return None
    _, run = c.call("POST", "/task-runs", {"template_id": tpl["id"]})
    return run if isinstance(run, dict) else None


def d3_write(c: Client) -> list[dict]:
    out: list[dict] = []
    c.call("PUT", "/settings", {"values": {"robot.write_enabled": True}})
    run = _make_run(c, 1)
    if not run:
        out.append(check("能建演练任务", False, "模板/计划创建失败", "D3"))
        return out

    t0 = time.time()
    code, body = c.call("POST", f"/task-runs/{run['id']}/dispatch")
    dt = round(time.time() - t0, 2)
    out.append(check("单点任务下发成功", code == 200 and isinstance(body, dict)
                     and body.get("status") == "running",
                     f"HTTP {code} {dt}s status={body.get('status') if isinstance(body, dict) else body}", "D3"))

    code, paused = c.call("POST", f"/task-runs/{run['id']}/pause")
    out.append(check("暂停", code == 200 and bool(paused.get("paused")), f"HTTP {code}", "D3"))
    code, resumed = c.call("POST", f"/task-runs/{run['id']}/resume")
    out.append(check("继续", code == 200 and not resumed.get("paused"), f"HTTP {code}", "D3"))
    code, cancelled = c.call("POST", f"/task-runs/{run['id']}/cancel")
    out.append(check("取消", code == 200 and cancelled.get("status") == "cancelled", f"HTTP {code}", "D3"))

    code, body = c.call("POST", f"/task-runs/{run['id']}/pause")
    out.append(check("非法状态操作被拒", code == 400, f"对已取消任务暂停 → HTTP {code}", "D3"))
    c.call("PUT", "/settings", {"values": {"robot.write_enabled": False}})
    return out


def d4_route(c: Client) -> list[dict]:
    c.call("PUT", "/settings", {"values": {"robot.write_enabled": True}})
    ok = 0
    for _ in range(3):
        run = _make_run(c, 5)
        if not run:
            continue
        code, _body = c.call("POST", f"/task-runs/{run['id']}/dispatch")
        if code == 200:
            ok += 1
            c.call("POST", f"/task-runs/{run['id']}/cancel")
    c.call("PUT", "/settings", {"values": {"robot.write_enabled": False}})
    return [check("5 点位路线连续下发", ok >= 3, f"{ok}/3 成功", "D4"),
            check("急停/挪动/断网/低电量分支", None, "需要真机配合操作", "D4")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="admin123")
    ap.add_argument("--minutes", type=float, default=2)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    c = Client(args.base)
    c.login(args.user, args.password)

    rows: list[dict] = []
    rows += d1_readonly(c)
    rows += d2_soak(c, args.minutes)
    rows += d3_write(c)
    rows += d4_route(c)

    passed = sum(1 for r in rows if r["result"] == PASS)
    failed = sum(1 for r in rows if r["result"] == FAIL)
    manual = sum(1 for r in rows if r["result"] == MANUAL)

    lines = [
        f"# 联调预案演练报告 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"> 目标：{args.base}　执行人：{args.user}",
        f"> 结果：通过 {passed} / 失败 {failed} / 需真机 {manual}",
        "",
        "| 阶段 | 检查项 | 结果 | 说明 |",
        "|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['section']} | {r['name']} | {r['result']} | {r['detail']} |")
    lines += [
        "",
        "## 演练结论",
        "",
        "- 自动可跑的检查项已全部纳入脚本，11-10 换 `--base` 指向真机环境即可复用；",
        "- 标「需真机/人工」的项必须现场做，脚本不能替代（拔网线、急停、挪动机器人）；",
        "- 失败项按预案第 4 节回退矩阵处理。",
    ]
    text = "\n".join(lines)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"\n已写入 {args.out}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
