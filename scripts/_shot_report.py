"""截图任务列表的「报告」按钮。"""

import glob
import os
from playwright.sync_api import sync_playwright

exe = sorted(glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-*\chrome-win64\chrome.exe")))[-1]
out = r"D:\Desktop\防爆机器人\docs\screenshots"

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=exe, headless=True,
                          args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
    pg = b.new_context(viewport={"width": 1600, "height": 900}).new_page()
    pg.goto("http://127.0.0.1:5173/login", wait_until="domcontentloaded", timeout=30000)
    pg.fill('input[autocomplete="off"]', "admin")
    pg.fill('input[type="password"]', "admin123")
    pg.click("button.submit")
    pg.wait_for_timeout(3500)
    pg.goto("http://127.0.0.1:5173/task-runs", wait_until="domcontentloaded")
    pg.wait_for_timeout(4000)
    print("报告按钮:", pg.locator("button", has_text="报告").count())
    pg.screenshot(path=os.path.join(out, "task-runs-report.png"))
    b.close()
