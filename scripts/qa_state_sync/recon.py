"""QA recon: log in, walk every route, dump visible buttons + network failures + screenshot.

Read-only: navigation and hover only, no button clicks here.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVID = os.path.join(ROOT, "docs", "reviews", "qa-evidence")
os.makedirs(EVID, exist_ok=True)

EXE = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1243\chrome-win64\chrome.exe")
BASE = "http://127.0.0.1:5173"

ROUTES = [
    ("dashboard", "/dashboard"),
    ("robot-status", "/robot-status"),
    ("map", "/map"),
    ("video", "/video"),
    ("room", "/room"),
    ("env", "/env"),
    ("tasks", "/tasks"),
    ("task-templates", "/task-templates"),
    ("task-runs", "/task-runs"),
    ("points", "/points"),
    ("inspection", "/inspection"),
    ("task-calendar", "/task-calendar"),
    ("alarms", "/alarms"),
    ("work-orders", "/work-orders"),
    ("ai-results", "/ai-results"),
    ("alarm-rules", "/alarm-rules"),
    ("history-tasks", "/history/tasks"),
    ("history-alarms", "/history/alarms"),
    ("reports", "/reports"),
    ("run-data", "/run-data"),
    ("robots", "/robots"),
    ("cameras", "/cameras"),
    ("env-device", "/env-device"),
    ("sensor-gateways", "/sensor-gateways"),
    ("record-plan", "/record/plan"),
    ("record-playback", "/record/playback"),
    ("messages", "/messages"),
    ("users", "/users"),
    ("settings", "/settings"),
    ("notify", "/notify"),
    ("oplog", "/oplog"),
    ("api-keys", "/keys"),
    ("m-task-1", "/m/task/1"),
    ("m-wo-1", "/m/wo/1"),
]

JS_DUMP = r"""
() => {
  const vis = (el) => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.visibility !== 'hidden' && s.display !== 'none' && r.width > 0 && r.height > 0;
  };
  const buttons = [...document.querySelectorAll('button, [role="button"], a.btn, input[type=button], input[type=submit]')]
    .filter(vis)
    .map((el, i) => {
      const r = el.getBoundingClientRect();
      return {
        i, tag: el.tagName.toLowerCase(),
        text: (el.innerText || el.value || '').trim().replace(/\s+/g, ' ').slice(0, 80),
        cls: (el.className && el.className.toString().slice(0, 80)) || '',
        disabled: !!(el.disabled || el.getAttribute('aria-disabled') === 'true'),
        title: el.getAttribute('title') || '',
        x: Math.round(r.x), y: Math.round(r.y),
      };
    });
  const inputs = [...document.querySelectorAll('input,select,textarea')].filter(vis).map(el => ({
    tag: el.tagName.toLowerCase(), type: el.getAttribute('type') || '',
    name: el.getAttribute('name') || '', placeholder: el.getAttribute('placeholder') || '',
    label: (el.closest('label')?.innerText || '').trim().slice(0, 40),
    value: (el.value || '').slice(0, 60),
  }));
  return { buttons, inputs, text: (document.body.innerText || '').slice(0, 4000) };
}
"""


def main() -> None:
    out = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=EXE)
        ctx = browser.new_context(viewport={"width": 1680, "height": 950}, ignore_https_errors=True)
        page = ctx.new_page()
        console = []
        bad = []
        page.on("console", lambda m: console.append({"type": m.type, "text": m.text[:300]}))
        page.on("pageerror", lambda e: console.append({"type": "pageerror", "text": str(e)[:300]}))
        page.on("response", lambda r: bad.append({"url": r.url, "status": r.status})
                if r.status >= 400 else None)

        page.goto(BASE + "/login", wait_until="domcontentloaded")
        page.fill('input[autocomplete="username"]', "admin")
        page.fill('input[type="password"]', "admin123")
        page.click("button.submit")
        page.wait_for_timeout(1500)
        print("after login:", page.url)

        for name, path in ROUTES:
            console.clear()
            bad.clear()
            started = time.time()
            try:
                page.goto(BASE + path, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(1800)
                try:
                    page.wait_for_load_state("networkidle", timeout=2500)
                except Exception:
                    pass
                page.wait_for_timeout(300)
                data = page.evaluate(JS_DUMP)
                shot = os.path.join(EVID, f"{name}.png")
                page.screenshot(path=shot, full_page=False)
                out[path] = {
                    "name": name,
                    "url": page.url,
                    "heading": page.title(),
                    "load_ms": int((time.time() - started) * 1000),
                    "buttons": data["buttons"],
                    "inputs": data["inputs"],
                    "text": data["text"],
                    "console": [c for c in console if c["type"] in ("error", "warning", "pageerror")],
                    "http_errors": bad[:40],
                    "screenshot": os.path.relpath(shot, ROOT).replace("\\", "/"),
                }
                print(f"{name:16s} btns={len(data['buttons']):3d} err={len(out[path]['console']):2d} "
                      f"http4xx5xx={len(bad):2d} {out[path]['load_ms']}ms")
            except Exception as e:  # noqa: BLE001
                out[path] = {"name": name, "error": repr(e)}
                print(f"{name:16s} FAILED {e!r}")

        with open(os.path.join(ROOT, "scripts", "qa_state_sync", "recon.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
