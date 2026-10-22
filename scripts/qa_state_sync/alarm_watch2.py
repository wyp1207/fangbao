"""90s alarm/WO growth watch used for the post-fix retest."""
import datetime
import json
import time
from collections import Counter

import requests

A = "http://127.0.0.1:8000/api/v1"
s = requests.Session()
s.post(A + "/auth/login", json={"username": "admin", "password": "admin123"})
rows, prev = [], None
for _ in range(4):
    t = datetime.datetime.now().isoformat(timespec="seconds")
    al = s.get(A + "/alarms?limit=200", timeout=15).json()
    wo = s.get(A + "/work-orders?limit=1", timeout=15).json()
    items = al["items"]
    op = [a for a in items if not a.get("closed_at")]
    row = {
        "t": t,
        "total": al["total"],
        "open": len(op),
        "wo": wo["total"],
        "top": Counter((a["robot_id"], a["metric"]) for a in op).most_common(4),
        "latest": [(a["id"], a["robot_id"], a["metric"], a["started_at"], a["message"][:40])
                   for a in items[:2]],
        "d_total": None if prev is None else al["total"] - prev[0],
        "d_wo": None if prev is None else wo["total"] - prev[1],
    }
    print(json.dumps(row, ensure_ascii=False), flush=True)
    rows.append(row)
    prev = (al["total"], wo["total"])
    time.sleep(30)

with open("scripts/qa_state_sync/alarm_watch2.json", "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False, indent=2)
