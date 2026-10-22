"""QA click audit — clicks every safe button on every page, records what happens.

Read-only policy: destructive / mutating buttons are NOT clicked. They are reported as
skipped with the reason. Modal-opening buttons are clicked, the modal is inspected and
cancelled. All network traffic caused by a click is recorded.
"""
from __future__ import annotations

import json
import os
import re
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXE = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1243\chrome-win64\chrome.exe")
BASE = "http://127.0.0.1:5173"
OUT = os.path.join(ROOT, "scripts", "qa_state_sync")

# Per-page labels that must NOT be clicked (write / external side effect).
SKIP: dict[str, str] = {
    "dashboard": r"云台控制|车体控制",
    "video": r"测试连通",
    "room": r"测试连通",
    "tasks": r"^(▶|■|下发|暂停|继续|取消当前任务)$",
    "task-runs": r"^巡航$",
    "inspection": r"^(生成任务|完成)$",
    "alarms": r"^(✓|→)$",
    "work-orders": r"^↑$",
    "robots": r"^🗑$",
    "cameras": r"^(⚡|⇄|⏸|🗑)$",
    "env-device": r"^🗑$",
    "sensor-gateways": r"^(测试|🗑)$",
    "record-plan": r"^(开始录制|停止)$",
    "record-playback": r"^🗑$",
    "messages": r"^全部标为已读$",
    "users": r"^(⏸|🗑)$",
    "notify": r"^(测试|⏸|🗑)$",
    "api-keys": r"^🗑$",
    "m-task-1": r"^(正常|异常|跳过|完成本次巡检（2/2）)$",
}

PAGES = [
    ("dashboard", "/dashboard"), ("robot-status", "/robot-status"), ("map", "/map"),
    ("video", "/video"), ("room", "/room"), ("env", "/env"), ("tasks", "/tasks"),
    ("task-templates", "/task-templates"), ("task-runs", "/task-runs"), ("points", "/points"),
    ("inspection", "/inspection"), ("task-calendar", "/task-calendar"), ("alarms", "/alarms"),
    ("work-orders", "/work-orders"), ("ai-results", "/ai-results"),
    ("alarm-rules", "/alarm-rules"), ("history-tasks", "/history/tasks"),
    ("history-alarms", "/history/alarms"), ("reports", "/reports"), ("run-data", "/run-data"),
    ("robots", "/robots"), ("cameras", "/cameras"), ("env-device", "/env-device"),
    ("sensor-gateways", "/sensor-gateways"), ("record-plan", "/record/plan"),
    ("record-playback", "/record/playback"), ("messages", "/messages"), ("users", "/users"),
    ("settings", "/settings"), ("notify", "/notify"), ("oplog", "/oplog"), ("api-keys", "/keys"),
    ("m-task-1", "/m/task/1"), ("m-wo-1", "/m/wo/1"),
]

COLLECT = r"""
() => {
  const vis = (el) => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.visibility !== 'hidden' && s.display !== 'none' && r.width > 1 && r.height > 1
      && r.bottom > 0 && r.top < innerHeight;
  };
  const inChrome = (el) => !!el.closest('.hdr, .nav-drop, .um-modal');
  document.querySelectorAll('[data-qa]').forEach(e => e.removeAttribute('data-qa'));
  const out = [];
  const els = [...document.querySelectorAll('button, [role="button"], a.btn')]
    .filter(el => vis(el) && !inChrome(el) && !el.disabled);
  els.forEach((el, i) => {
    const text = (el.innerText || el.value || '').trim().replace(/\s+/g, ' ');
    const key = (el.getAttribute('title') || text || '').slice(0, 60);
    if (!key) return;
    el.setAttribute('data-qa', String(i));
    out.push({ idx: String(i), text: text.slice(0, 60), key,
               title: el.getAttribute('title') || '',
               cls: (el.className && el.className.toString().slice(0, 60)) || '',
               tag: el.tagName.toLowerCase() });
  });
  return out;
}
"""

TEXT_COLLECT = r"""
() => {
  const vis = (el) => { const s=getComputedStyle(el); const r=el.getBoundingClientRect(); return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0; };
  const toast = [...document.querySelectorAll('.toast')].filter(vis).map(e=>e.innerText.trim());
  const modal = [...document.querySelectorAll('[role=dialog], .modal, .modal-mask, .um-modal')].filter(vis)
      .map(e => e.innerText.trim().slice(0, 600));
  return { text: document.body.innerText.slice(0, 8000), toast, modal, url: location.href };
}
"""


def main() -> None:
    result: dict[str, list] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=EXE)
        ctx = browser.new_context(viewport={"width": 1680, "height": 950}, accept_downloads=True)
        page = ctx.new_page()
        net: list = []
        dialogs: list = []
        downloads: list = []
        popups: list = []
        page.on("response", lambda r: net.append({"m": r.request.method, "u": r.url.replace(BASE, ""),
                                                   "s": r.status}))
        page.on("dialog", lambda d: (dialogs.append({"type": d.type, "msg": d.message}),
                                     d.dismiss()))
        page.on("download", lambda d: downloads.append(d.suggested_filename))
        ctx.on("page", lambda pg: (popups.append(pg.url), pg.close()))

        page.goto(BASE + "/login", wait_until="domcontentloaded")
        page.fill('input[autocomplete="username"]', "admin")
        page.fill('input[type="password"]', "admin123")
        page.click("button.submit")
        page.wait_for_timeout(1500)

        for name, path in PAGES:
            print(f"\n== {name}")
            entries: list = []
            try:
                page.goto(BASE + path, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(1600)
                skip_re = re.compile(SKIP.get(name, r"$^"))
                seen: dict[str, int] = {}
                for _ in range(30):
                    cands = page.evaluate(COLLECT)
                    pick = None
                    for c in cands:
                        k = c["key"]
                        if skip_re.search(c["text"]) or skip_re.search(c["title"]):
                            continue
                        if seen.get(k, 0) >= 2:
                            continue
                        pick = c
                        seen[k] = seen.get(k, 0) + 1
                        break
                    if pick is None:
                        break
                    before = page.evaluate(TEXT_COLLECT)
                    net.clear(); dialogs.clear(); downloads.clear(); popups.clear()
                    err = None
                    try:
                        page.evaluate(
                            "(i) => { const el = document.querySelector('[data-qa=\"' + i + '\"]'); if (el) el.click(); }",
                            pick["idx"])
                    except Exception as e:  # noqa: BLE001
                        err = repr(e)
                    page.wait_for_timeout(850)
                    after = page.evaluate(TEXT_COLLECT)
                    old_lines = set(before["text"].splitlines())
                    new_lines = [ln.strip() for ln in after["text"].splitlines()
                                 if ln.strip() and ln.strip() not in old_lines][:12]
                    rec = {
                        "button": pick["text"] or pick["title"],
                        "title": pick["title"], "cls": pick["cls"],
                        "url_changed": after["url"] != before["url"],
                        "new_url": after["url"] if after["url"] != before["url"] else None,
                        "new_text": new_lines,
                        "toast": after["toast"],
                        "modal": [m[:400] for m in after["modal"]],
                        "net": [n for n in net if "/api/" in n["u"]][:12],
                        "dialog": list(dialogs), "downloads": list(downloads),
                        "popups": list(popups), "error": err,
                    }
                    entries.append(rec)
                    print(f"  [{rec['button']}] toast={rec['toast']} modal={len(rec['modal'])} "
                          f"net={[(n['m'], n['s'], n['u'].split('?')[0]) for n in rec['net']]} "
                          f"dl={rec['downloads']} dlg={rec['dialog']}")
                    if rec["url_changed"]:
                        page.goto(BASE + path, wait_until="domcontentloaded", timeout=20000)
                        page.wait_for_timeout(1200)
                        continue
                    # close modal / dropdown, restore route
                    if after["modal"]:
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(200)
                        try:
                            btn = page.locator(".modal button, .modal-mask button, [role=dialog] button").filter(
                                has_text=re.compile(r"^(取消|关闭|知道了|返回)$")).first
                            if btn.count() and btn.is_visible():
                                btn.click(timeout=1000)
                        except Exception:
                            pass
                # record the skipped buttons too
                skipped = [c for c in page.evaluate(COLLECT)
                           if skip_re.search(c["text"]) or skip_re.search(c["title"])]
                result[path] = {"name": name, "clicked": entries,
                                "skipped": [{"text": s["text"], "title": s["title"]} for s in skipped]}
            except Exception as e:  # noqa: BLE001
                result[path] = {"name": name, "error": repr(e), "clicked": entries}
                print("  PAGE FAILED", repr(e))

        with open(os.path.join(OUT, "click_audit.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        ctx.close(); browser.close()


if __name__ == "__main__":
    main()
