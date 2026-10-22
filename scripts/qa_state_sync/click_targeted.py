"""Targeted read-only click checks for the pages not covered by the earlier pass."""
from __future__ import annotations

import json
import os

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXE = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1243\chrome-win64\chrome.exe")
BASE = "http://127.0.0.1:5173"
EVID = os.path.join(ROOT, "docs", "reviews", "qa-evidence")

CASES = [
    # path, button text, kind(modal/dropdown/nav/get/download), screenshot
    ("/robots", "新增设备", "modal", None),
    ("/robots", "✎", "modal", None),
    ("/robots", "⇄", "modal", None),
    ("/cameras", "新增视频源", "modal", None),
    ("/cameras", "✎", "modal", None),
    ("/env-device", "新增传感器", "modal", None),
    ("/env-device", "✎", "modal", None),
    ("/sensor-gateways", "新增网关", "modal", None),
    ("/record/plan", "新增计划", "modal", "modal_record_plan.png"),
    ("/record/playback", "▶", "player", None),
    ("/record/playback", "⤓", "download", None),
    ("/messages", "查看", "nav", None),
    ("/users", "新建账号", "modal", "modal_user_new.png"),
    ("/users", "⚿", "modal", None),
    ("/notify", "新增通道", "modal", "modal_notify_new.png"),
    ("/notify", "✎", "modal", None),
    ("/keys", "新建密钥", "modal", "modal_apikey_new.png"),
    ("/settings", "重新探测", "get", None),
    ("/reports", "统计", "get", None),
    ("/reports", "导出 Excel", "download", None),
    ("/work-orders", "派给", "dropdown", None),
    ("/alarms", "✎", "modal", "modal_alarm_handle.png"),
    ("/alarms", "⏹", "modal", "modal_alarm_close.png"),
    ("/points", "查询", "get", None),
    ("/points", "重置", "get", None),
    ("/points", "同步到机器人", "modal", None),
    ("/map", "导入", "modal", None),
]


def main() -> None:
    out = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, executable_path=EXE)
        ctx = b.new_context(viewport={"width": 1680, "height": 950}, accept_downloads=True)
        pg = ctx.new_page()
        pg.goto(BASE + "/login", wait_until="domcontentloaded")
        pg.fill('input[autocomplete="username"]', "admin")
        pg.fill('input[type="password"]', "admin123")
        pg.click("button.submit")
        pg.wait_for_url("**/dashboard", timeout=10000)
        pg.wait_for_timeout(1000)

        for path, text, kind, shot in CASES:
            net, dl, dialogs = [], [], []
            pg.on("response", lambda r: net.append((r.request.method, r.url.replace(BASE, "").split("?")[0], r.status))
                  if "/api/" in r.url else None)
            pg.on("download", lambda d: dl.append(d.suggested_filename))
            pg.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
            rec = {"path": path, "button": text, "kind": kind}
            try:
                pg.goto(BASE + path, wait_until="domcontentloaded", timeout=20000)
                pg.wait_for_timeout(1800)
                loc = pg.locator("button, a.btn").filter(has_text=text)
                if not loc.count():
                    rec["error"] = "button not found"
                else:
                    before = pg.locator("body").inner_text()
                    rec["disabled"] = loc.first.is_disabled()
                    if rec["disabled"]:
                        rec["note"] = "disabled; not clicked"
                        out.append(rec); pg.close(); pg = ctx.new_page(); continue
                    net.clear(); dl.clear(); dialogs.clear()
                    loc.first.click(timeout=4000)
                    pg.wait_for_timeout(1200)
                    body = pg.locator("body").inner_text()
                    modal = pg.locator(".modal-mask, .um-modal").all_inner_texts() if pg.locator(".modal-mask, .um-modal").count() else []
                    rec.update({
                        "url": pg.url.replace(BASE, ""),
                        "toast": pg.locator(".toast").all_inner_texts(),
                        "modal": [m[:600] for m in modal],
                        "net": net[-8:],
                        "downloads": dl,
                        "dialogs": dialogs,
                        "new_text": [ln.strip() for ln in body.splitlines()
                                     if ln.strip() and ln.strip() not in set(before.splitlines())][:10],
                    })
                    if shot:
                        pg.screenshot(path=os.path.join(EVID, shot))
                    if modal:
                        pg.keyboard.press("Escape")
                        pg.wait_for_timeout(300)
            except Exception as e:  # noqa: BLE001
                rec["error"] = repr(e)[:200]
            out.append(rec)
            print(json.dumps(rec, ensure_ascii=False)[:700], flush=True)
            # remove listeners for next iteration by recreating page
            pg.close()
            pg = ctx.new_page()
        with open(os.path.join(ROOT, "scripts", "qa_state_sync", "click_targeted.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        ctx.close(); b.close()


if __name__ == "__main__":
    main()
