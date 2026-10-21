#!/usr/bin/env python3
"""一次真实浏览器冒烟：起后端(mock) + vite dev，登录进驾驶舱，截图。

用途：把“类型和模板编译通过”升级成“页面真的渲染出来了”。
不是 CI 测试，跑完就退出，服务也会被关掉。

用法（需要有可用的 chromium）：
    python scripts/smoke_web.py
产物：docs/screenshots/login.png、docs/screenshots/dashboard.png
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "docs" / "screenshots"
BACKEND_PORT = 8000
FRONTEND_PORT = 5199

BROWSERS = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"


def find_chrome() -> str:
    """用本机已下载的 chromium，避免再下一次 150MB。"""
    for pattern in ("chromium-*/chrome-win64/chrome.exe", "chromium-*/chrome-win/chrome.exe"):
        found = sorted(BROWSERS.glob(pattern), reverse=True)
        if found:
            return str(found[0])
    raise SystemExit(f"没找到 chromium，检查 {BROWSERS}")


def wait_http(url: str, timeout: float = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status < 500:
                    return
        except Exception:
            time.sleep(0.7)
    raise SystemExit(f"等不到 {url}")


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("JC_DB_URL", None)

    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(BACKEND_PORT)],
        cwd=ROOT / "server", env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    frontend = subprocess.Popen(
        ["npm", "run", "dev", "--", "--port", str(FRONTEND_PORT), "--strictPort",
         "--host", "127.0.0.1"],
        cwd=ROOT / "web", shell=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    from playwright.sync_api import sync_playwright

    errors: list[str] = []
    try:
        wait_http(f"http://127.0.0.1:{BACKEND_PORT}/health")
        wait_http(f"http://127.0.0.1:{FRONTEND_PORT}/")

        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=find_chrome(), headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))

            page.goto(f"http://127.0.0.1:{FRONTEND_PORT}/", wait_until="networkidle")
            page.screenshot(path=str(SHOTS / "login.png"))
            page.fill('input[autocomplete="username"]', "admin")
            page.fill('input[type="password"]', "admin123")
            page.click("button:has-text('登录')")
            page.wait_for_selector("canvas", timeout=20000)
            page.wait_for_timeout(2500)  # 让 1s 轮询跑两轮，地图和状态条有数据

            page.screenshot(path=str(SHOTS / "dashboard.png"), full_page=True)
            canvas = page.evaluate(
                "() => { const c = document.querySelector('canvas');"
                " return c ? [c.width, c.height] : null }"
            )
            text = page.inner_text("body")
            browser.close()

        # 登录页的 /auth/me 返回 401 是正常的“未登录”探测，不算错误
        real_errors = [e for e in errors if "401" not in e and "favicon" not in e]
        print(json.dumps({
            "login_shot": str(SHOTS / "login.png"),
            "dashboard_shot": str(SHOTS / "dashboard.png"),
            "canvas_px": canvas,
            "has_battery": "电量" in text,
            "has_online": "链路正常" in text or "通信中断" in text,
            "console_errors": real_errors[:5],
        }, ensure_ascii=False, indent=2))
        return 0 if canvas and canvas[0] > 0 and not real_errors else 1
    finally:
        # Windows 上 terminate() 只杀 shell，vite/uvicorn 的孙进程会漏下来占端口
        for proc in (frontend, backend):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, check=False)


if __name__ == "__main__":
    sys.exit(main())
