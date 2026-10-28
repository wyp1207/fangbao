"""前端冒烟：登录后逐个路由打开，记录控制台错误/请求失败/空白页。

用法：
  python scripts/ui_smoke.py                # 全部路由
  python scripts/ui_smoke.py --only alarms  # 只跑名字包含 alarms 的
输出：docs/reviews/ui-smoke.md（控制台错误按路由归类）
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5173"
ROUTES = [
    "dashboard", "robot-status", "map", "video", "room", "env",
    "tasks", "task-templates", "task-runs", "points", "inspection", "task-calendar",
    "alarms", "work-orders", "ai-results", "alarm-rules",
    "history/tasks", "history/alarms", "run-data", "reports",
    "robots", "peripherals", "cameras", "env-device", "sensor-gateways",
    "record/plan", "record/playback",
    "users", "settings", "notify", "oplog", "keys", "system-status", "device-keys", "messages",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    routes = [r for r in ROUTES if args.only in r]

    exe = sorted(glob.glob(os.path.expandvars(
        r"%LOCALAPPDATA%\ms-playwright\chromium-*\chrome-win64\chrome.exe")))[-1]

    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe, headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()

        page.goto(f"{BASE}/login", wait_until="domcontentloaded", timeout=30000)
        page.fill('input[autocomplete="off"]', "admin")
        page.fill('input[type="password"]', "admin123")
        page.click("button.submit")
        page.wait_for_timeout(4500)

        for route in routes:
            errors: list[str] = []
            failures: list[str] = []

            def on_console(msg, bucket=errors):
                if msg.type in ("error", "warning") and "favicon" not in msg.text:
                    bucket.append(msg.text[:160])

            def on_response(resp, bucket=failures):
                if "/api/v1" in resp.url and resp.status >= 400:
                    bucket.append(f"{resp.status} {resp.url.split('/api/v1')[-1][:70]}")

            page.on("console", on_console)
            page.on("response", on_response)
            try:
                page.goto(f"{BASE}/{route}", wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2500)
                text = page.locator("body").inner_text().strip()
                blank = len(text) < 40
                rows.append({"route": route, "blank": blank, "errors": errors[:3], "failed": failures[:3]})
            except Exception as exc:  # noqa: BLE001
                rows.append({"route": route, "blank": True, "errors": [f"打开失败 {exc.__class__.__name__}"],
                             "failed": []})
            finally:
                page.remove_listener("console", on_console)
                page.remove_listener("response", on_response)

        browser.close()

    bad = [r for r in rows if r["blank"] or r["errors"] or r["failed"]]
    print(f"共 {len(rows)} 个路由，有问题 {len(bad)} 个")
    for r in bad:
        print(f"\n/{r['route']}" + ("（空白页）" if r["blank"] else ""))
        for e in r["errors"]:
            print(f"  console: {e}")
        for f in r["failed"]:
            print(f"  api: {f}")

    out = os.path.join("docs", "reviews", "ui-smoke.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("# 前端冒烟结果\n\n")
        fh.write(f"共 {len(rows)} 个路由，**有问题 {len(bad)} 个**（空白页 / 控制台报错 / 接口 4xx-5xx）。\n\n")
        fh.write("| 路由 | 空白 | 控制台错误 | 接口失败 |\n|---|---|---|---|\n")
        for r in rows:
            mark = "❌" if r["blank"] else "OK"
            err = "<br>".join(r["errors"]) or "—"
            fail = "<br>".join(r["failed"]) or "—"
            fh.write(f"| `/{r['route']}` | {mark} | {err} | {fail} |\n")
    print(f"\n已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
