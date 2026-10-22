import json, os
from playwright.sync_api import sync_playwright
ROOT=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXE=os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1243\chrome-win64\chrome.exe")
BASE="http://127.0.0.1:5173"; EVID=os.path.join(ROOT,"docs","reviews","qa-evidence")
CASES=[("/notify","新增通道"),("/notify","✎"),("/keys","新建密钥"),("/settings","重新探测"),
       ("/reports","统计"),("/reports","导出 Excel"),("/work-orders","派给"),
       ("/alarms","✎"),("/alarms","⏹"),("/points","同步到机器人"),("/map","导入")]
out=[]
with sync_playwright() as p:
    b=p.chromium.launch(headless=True, executable_path=EXE)
    for path,text in CASES:
        ctx=b.new_context(viewport={"width":1680,"height":950}, accept_downloads=True)
        pg=ctx.new_page(); net=[]; dl=[]; dialogs=[]; files=[]
        pg.on("response", lambda r: net.append((r.request.method,r.url.replace(BASE,"").split("?")[0],r.status)) if "/api/" in r.url else None)
        pg.on("download", lambda d: dl.append(d.suggested_filename))
        pg.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
        pg.on("filechooser", lambda fc: files.append("filechooser"))
        rec={"path":path,"button":text}
        try:
            pg.goto(BASE+"/login"); pg.fill('input[autocomplete="username"]','admin'); pg.fill('input[type=password]','admin123'); pg.click('button.submit')
            pg.wait_for_url("**/dashboard",timeout=10000)
            pg.goto(BASE+path); pg.wait_for_timeout(1800)
            loc=pg.locator("button, a.btn").filter(has_text=text)
            if not loc.count(): rec["error"]="not found"
            else:
                rec["disabled"]=loc.first.is_disabled()
                if rec["disabled"]: rec["note"]="disabled; not clicked"
                else:
                    net.clear(); dl.clear(); dialogs.clear(); files.clear()
                    loc.first.click(timeout=5000); pg.wait_for_timeout(1200)
                    modal=pg.locator(".modal-mask, .um-modal").all_inner_texts() if pg.locator(".modal-mask, .um-modal").count() else []
                    rec.update({"url":pg.url.replace(BASE,""),"toast":pg.locator(".toast").all_inner_texts(),
                                "modal":[m[:600] for m in modal],"net":net[-8:],"downloads":dl,
                                "dialogs":dialogs,"files":files})
                    if text=="新建密钥": pg.screenshot(path=os.path.join(EVID,"modal_apikey_new.png"))
                    if text=="新增通道": pg.screenshot(path=os.path.join(EVID,"modal_notify_new.png"))
                    if text=="✎" and path=="/alarms": pg.screenshot(path=os.path.join(EVID,"modal_alarm_handle.png"))
                    if text=="⏹": pg.screenshot(path=os.path.join(EVID,"modal_alarm_close.png"))
        except Exception as e: rec["error"]=repr(e)[:200]
        print(json.dumps(rec,ensure_ascii=False)[:800],flush=True)
        out.append(rec); ctx.close()
    b.close()
json.dump(out,open(os.path.join(ROOT,"scripts","qa_state_sync","click_targeted2.json"),"w",encoding="utf-8"),ensure_ascii=False,indent=2)
