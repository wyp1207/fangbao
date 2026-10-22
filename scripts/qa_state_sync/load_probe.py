"""QA load probe: 20 concurrent requests per endpoint + 100 sequential polls.

Read-only GETs only. Reports p50/p95/max, HTTP error count and any 5xx.
"""
from __future__ import annotations

import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import requests

API = "http://127.0.0.1:8000/api/v1"
ENDPOINTS = [
    "/robots/1/status",
    "/alarms",
    "/reports/summary",
    "/telemetry?hours=1",
]


def login() -> requests.Session:
    s = requests.Session()
    r = s.post(API + "/auth/login", json={"username": "admin", "password": "admin123"}, timeout=10)
    r.raise_for_status()
    return s


def pct(vals: list[float], p: float) -> float:
    if not vals:
        return float("nan")
    vals = sorted(vals)
    k = min(len(vals) - 1, max(0, int(round((p / 100) * len(vals) - 0.5))))
    return round(vals[k] * 1000, 1)


def main() -> None:
    s = login()
    cookie = s.cookies.get_dict()
    out: dict = {}

    def one(ep: str) -> dict:
        t0 = time.perf_counter()
        try:
            r = requests.get(API + ep, cookies=cookie, timeout=30)
            return {"ep": ep, "ms": (time.perf_counter() - t0) * 1000,
                    "status": r.status_code, "len": len(r.content)}
        except Exception as e:  # noqa: BLE001
            return {"ep": ep, "ms": (time.perf_counter() - t0) * 1000,
                    "status": -1, "err": str(e)[:100]}

    print("== 20 concurrent per endpoint")
    for ep in ENDPOINTS:
        with ThreadPoolExecutor(max_workers=20) as ex:
            res = list(ex.map(lambda _: one(ep), range(20)))
        lat = [r["ms"] for r in res]
        codes: dict[int, int] = {}
        for r in res:
            codes[r["status"]] = codes.get(r["status"], 0) + 1
        row = {"n": 20, "p50_ms": pct(lat, 50), "p95_ms": pct(lat, 95),
               "max_ms": round(max(lat), 1), "min_ms": round(min(lat), 1),
               "codes": {str(k): v for k, v in codes.items()},
               "bytes_avg": int(statistics.mean(r["len"] for r in res if r.get("len") is not None))}
        out[ep] = row
        print(ep, json.dumps(row, ensure_ascii=False))

    print("== 100 sequential polls (/robots/1/status, 200ms apart)")
    series = []
    for i in range(100):
        series.append(one("/robots/1/status"))
        time.sleep(0.2)
    lat = [r["ms"] for r in series]
    p95v = pct(lat, 95)
    spine = [{"i": i, "ms": round(r["ms"], 1), "status": r["status"]}
             for i, r in enumerate(series) if r["ms"] > max(p95v * 2, 200)]
    codes: dict[int, int] = {}
    for r in series:
        codes[r["status"]] = codes.get(r["status"], 0) + 1
    row = {"n": 100, "p50_ms": pct(lat, 50), "p95_ms": pct(lat, 95),
           "max_ms": round(max(lat), 1), "codes": {str(k): v for k, v in codes.items()},
           "spikes_gt_2xp95": spine[:10], "spike_count": len(spine)}
    out["seq100_status"] = row
    print(json.dumps(row, ensure_ascii=False))

    print("== 100 sequential polls (/alarms, 200ms apart)")
    series = []
    for i in range(100):
        series.append(one("/alarms"))
        time.sleep(0.2)
    lat = [r["ms"] for r in series]
    codes = {}
    for r in series:
        codes[r["status"]] = codes.get(r["status"], 0) + 1
    row = {"n": 100, "p50_ms": pct(lat, 50), "p95_ms": pct(lat, 95),
           "max_ms": round(max(lat), 1), "codes": {str(k): v for k, v in codes.items()},
           "spike_count": sum(1 for x in lat if x > max(pct(lat, 95) * 2, 200))}
    out["seq100_alarms"] = row
    print(json.dumps(row, ensure_ascii=False))

    with open("scripts/qa_state_sync/load_probe.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
