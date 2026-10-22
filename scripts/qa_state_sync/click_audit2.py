"""QA click audit v2 — one fresh page load per button, so clicks never contaminate each other.

Read-only: SKIP mutating buttons; modal-opening buttons are clicked and the modal text is
recorded. Every click gets a clean page.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXE = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1243\chrome-win64\chrome.exe")
BASE = "http://127.0.0.1:5173"
OUT = os.path.join(ROOT, "scripts", "qa_state_sync")

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
    const s = getComputedStyle(el); const r = el.getBoundingClientRect();
    return s.visibility !== 'hidden' && s.display !== 'none' && r.width > 1 && r.height > 1
      && r.bottom > 0 && r.top < innerHeight;
  };
  const inChrome = (el) => !!el.closest('.hdr, .nav-drop, .um-modal');
  document.querySelectorAll('[data-qa]').forEach(e => e.removeAttribute('data-qa'));
  const out = [];
  [...document.querySelectorAll('button, [role="button"], a.btn')]
    .filter(el => vis(el) && !inChrome(el) && !el.disabled)
    .forEach((el, i) => {
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
  const modal = [...document.querySelectorAll('.modal-mask, .um-modal, .drawer')].filter(vis)
      .map(e => e.innerText.trim().slice(0, 700));
  return { text: document.body.innerText.slice(0, 9000), toast, modal, url: location.href };
}
"""


def wait_backend(timeout: int = 150) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(2)
    return False


def audit_page(ctx, name: str, path: str, out: dict, login_page=None) -> None:
    print(f"\n== {name}", flush=True)
    if not wait_backend():
        out[path] = {"name": name, "error": "backend down >150s", "clicks": [], "skipped": []}
        return
    skips: list = []
    clicks: list = []
    skip_re = re.compile(SKIP.get(name, r"$^"))
    cands: list = []
    try:
        page = ctx.new_page()
        page.goto(BASE + path, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(1600)
        allb = page.evaluate(COLLECT)
        for c in allb:
            if skip_re.search(c["text"]) or skip_re.search(c["title"]):
                if not any(s["key"] == c["key"] for s in skips):
                    skips.append(c)
            elif not any(k["key"] == c["key"] for k in cands):
                cands.append(c)
        page.close()
    except Exception as e:  # noqa: BLE001
        out[path] = {"name": name, "error": f"load: {e!r}", "clicks": [], "skipped": []}
        print("  LOAD FAILED", repr(e))
        return

    for c in cands[:14]:
        page = ctx.new_page()
        net: list = []
        dialogs: list = []
        downloads: list = []
        page.on("response", lambda r: net.append({"m": r.request.method,
                                                  "u": r.url.replace(BASE, "").split("?")[0],
                                                  "s": r.status})
                if "/api/" in r.url else None)
        page.on("dialog", lambda d: (dialogs.append({"type": d.type, "msg": d.message}), d.dismiss()))
        page.on("download", lambda d: downloads.append(d.suggested_filename))
        err = None
        try:
            page.goto(BASE + path, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1500)
            before = page.evaluate(TEXT_COLLECT)
            # element may be gone after reload; find by key again
            target = None
            for cand in page.evaluate(COLLECT):
                if cand["key"] == c["key"]:
                    target = cand
                    break
            if target is None:
                clicks.append({"button": c["text"], "title": c["title"], "error": "not found after reload"})
                page.close(); continue
            net.clear()
            page.evaluate("(i) => { const el = document.querySelector('[data-qa=\"' + i + '\"]'); if (el) el.click(); }",
                          target["idx"])
            page.wait_for_timeout(900)
            after = page.evaluate(TEXT_COLLECT)
            extra = []
            for pg in ctx.pages:
                if pg is not page and pg is not login_page:
                    try:
                        extra.append(pg.url.replace(BASE, ""))
                        pg.close()
                    except Exception:
                        pass
            old = set(before["text"].splitlines())
            new_lines = [ln.strip() for ln in after["text"].splitlines()
                         if ln.strip() and ln.strip() not in old][:10]
            rec = {
                "button": target["text"] or target["title"], "title": target["title"],
                "cls": target["cls"],
                "url_changed": after["url"] != before["url"],
                "new_url": after["url"].replace(BASE, "") if after["url"] != before["url"] else None,
                "new_text": new_lines,
                "toast": after["toast"], "modal": [m[:500] for m in after["modal"]],
                "net": net[:10], "dialog": dialogs, "downloads": downloads, "error": None,
                "popups": extra,
            }
        except Exception as e:  # noqa: BLE001
            err = repr(e)
            rec = {"button": c["text"], "title": c["title"], "error": err}
        try:
            page.close()
        except Exception:
            pass
        clicks.append(rec)
        print(f"  [{rec.get('button')}] toast={rec.get('toast')} modal={len(rec.get('modal') or [])} "
              f"net={[(n['m'], n['s'], n['u']) for n in (rec.get('net') or [])]} "
              f"dl={rec.get('downloads')} err={rec.get('error')}", flush=True)
    out[path] = {"name": name, "clicks": clicks, "skipped": skips,
                 "loading_snapshot": page.evaluate("() => document.body.innerText.slice(0,500)") if False else ""}


def main() -> None:
    only = set(sys.argv[1:])
    out: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=EXE)
        ctx = browser.new_context(viewport={"width": 1680, "height": 950}, accept_downloads=True)
        page = ctx.new_page()
        page.goto(BASE + "/login", wait_until="domcontentloaded")
        page.fill('input[autocomplete="username"]', "admin")
        page.fill('input[type="password"]', "admin123")
        page.click("button.submit")
        page.wait_for_timeout(2500)
        if "/login" in page.url:
            print("LOGIN FAILED at", page.url)
            print(page.locator("body").inner_text()[:500])
            page.close(); browser.close(); return
        login_page = page
        for name, path in PAGES:
            if only and name not in only:
                continue
            try:
                audit_page(ctx, name, path, out, login_page)
            except Exception as e:  # noqa: BLE001
                out[path] = {"name": name, "error": repr(e), "clicks": [], "skipped": []}
                print("  SKIP PAGE", repr(e))
            with open(os.path.join(OUT, "click_audit.json"), "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
        ctx.close(); browser.close()


if __name__ == "__main__":
    main()
