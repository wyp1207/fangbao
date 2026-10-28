"""10 分钟浸泡测试：持续请求 + 周期性业务操作，查内存/错误/审计链。

比联调套件的 A4 更长，用来在真机前先排除"跑一会儿就崩"的问题。
用法：python scripts/soak_10min.py [--minutes 10]
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import threading
import time

import requests

BASE = "http://127.0.0.1:8000/api/v1"


def mem_mb(pid: int) -> float:
    try:
        import psutil

        return psutil.Process(pid).memory_info().rss / 1024 / 1024
    except Exception:  # noqa: BLE001
        return -1


def find_pid() -> int:
    import subprocess

    out = subprocess.check_output(
        ["powershell", "-NoProfile", "-Command",
         "(Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess"], text=True)
    return int(out.strip().splitlines()[0])


def login():
    s = requests.Session()
    r = s.post(BASE + "/auth/login", json={"username": "admin", "password": "admin123"}, timeout=15)
    r.raise_for_status()
    s.headers.update({"X-CSRF-Token": r.json()["csrf_token"]})
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=10)
    args = ap.parse_args()
    s = login()
    pid = find_pid()
    t_end = time.time() + args.minutes * 60
    lat: list[float] = []
    errors = 0
    samples: list[float] = []
    n = 0
    while time.time() < t_end:
        for path in ("/alarms?limit=20", "/robots", "/sensors", "/task-runs?limit=10"):
            t0 = time.time()
            try:
                r = s.get(BASE + path, timeout=15)
                if r.status_code >= 400:
                    errors += 1
            except Exception:  # noqa: BLE001
                errors += 1
            lat.append((time.time() - t0) * 1000)
            n += 1
        if n % 200 < 4:
            samples.append(mem_mb(pid))
        time.sleep(0.2)

    lat.sort()
    print(f"请求 {n} 次，错误 {errors} 次")
    print(f"p50={statistics.median(lat):.0f}ms p95={lat[int(len(lat) * .95) - 1]:.0f}ms "
          f"max={lat[-1]:.0f}ms")
    if samples:
        print(f"内存：起始 {samples[0]:.1f}MB → 结束 {samples[-1]:.1f}MB "
              f"（峰值 {max(samples):.1f}MB）")
    body = s.get(BASE + "/audit-logs/verify", timeout=30).json()
    print("审计链：", body)
    ok = errors == 0 and body.get("ok") is True
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
