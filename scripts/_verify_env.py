import glob, os
from playwright.sync_api import sync_playwright
exe = sorted(glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-*\chrome-win64\chrome.exe")))[-1]
out = r"D:\Desktop\防爆机器人\docs\screenshots"
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=exe, headless=True,
        args=["--use-gl=angle","--use-angle=swiftshader","--enable-unsafe-swiftshader"])
    pg = b.new_context(viewport={"width":1600,"height":900}).new_page()
    errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("http://127.0.0.1:5173/login", wait_until="domcontentloaded", timeout=30000)
    pg.fill('input[autocomplete="off"]', "admin"); pg.fill('input[type="password"]', "admin123")
    pg.click("button.submit"); pg.wait_for_timeout(4000)
    pg.goto("http://127.0.0.1:5173/dashboard", wait_until="domcontentloaded"); pg.wait_for_timeout(6000)
    rt = pg.locator(".rt").bounding_box(); box = pg.locator(".map-frame").bounding_box()
    print("rt:", round(rt["height"]), "y=", round(rt["y"]), "| map:", round(box["height"]))
    rows = pg.locator(".rt-line b"); clipped=0
    for i in range(rows.count()):
        d=rows.nth(i).evaluate("el=>({sw:el.scrollWidth,cw:el.clientWidth,sh:el.scrollHeight,ch:el.clientHeight,t:el.textContent.trim()})")
        if d["sw"]>d["cw"]+1 or d["sh"]>d["ch"]+1:
            clipped+=1; print(" clipped:", d)
    print("task rows:", rows.count(), "clipped:", clipped)
    print("env cells:", pg.locator(".env-cell").count(), "texts:", pg.locator(".env-label").all_inner_texts())
    print("stale:", pg.locator(".env-cell.stale").count())
    pg.screenshot(path=os.path.join(out, "dashboard-env-fixed.png"))
    b.close()
print("page errors:", errs[:3] or "none")
