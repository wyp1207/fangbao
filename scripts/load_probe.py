"""并发/延迟/一致性探针（标准库，够用就好）。

用法：
    python scripts/load_probe.py --base http://127.0.0.1:8000 --concurrency 20 --rounds 5
输出：每个接口的 p50/p95/max/错误数，以及两处数据是否一致。
ponytail: 单机 HTTP 压测，不做长连接/限流建模；只回答"现在卡不卡、数据对不对"。
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import CookieJar


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = ""

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, object, float]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.base}/api/v1{path}", data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.csrf:
            req.add_header("X-CSRF-Token", self.csrf)
        t0 = time.perf_counter()
        try:
            with self.opener.open(req, timeout=30) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {}), time.perf_counter() - t0
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")[:200], time.perf_counter() - t0
        except Exception as exc:  # noqa: BLE001
            return 0, f"{exc.__class__.__name__}: {exc}", time.perf_counter() - t0

    def login(self, user: str, password: str) -> None:
        code, body, _ = self.call("POST", "/auth/login", {"username": user, "password": password})
        if code != 200:
            raise SystemExit(f"登录失败 {code} {body}")
        self.csrf = body.get("csrf_token", "")


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = min(len(values) - 1, int(len(values) * p))
    return values[idx] * 1000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="admin123")
    ap.add_argument("--concurrency", type=int, default=20)
    ap.add_argument("--rounds", type=int, default=5)
    args = ap.parse_args()

    paths = ["/robots/1/status", "/robots/2/status", "/alarms?limit=20",
             "/reports/summary", "/telemetry?hours=6&points=120",
             "/task-runs?limit=20", "/work-orders?limit=20", "/devices"]

    c = Client(args.base)
    c.login(args.user, args.password)

    print(f"并发 {args.concurrency} × 轮 {args.rounds}，接口 {len(paths)} 个\n")
    print(f"{'接口':30s} {'p50(ms)':>8s} {'p95(ms)':>8s} {'max(ms)':>8s} {'错误':>5s}")
    summary = {}
    for path in paths:
        times: list[float] = []
        errors = 0
        def hit(_):
            code, _body, dt = c.call("GET", path)
            return code, dt
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            for _round in range(args.rounds):
                for code, dt in pool.map(hit, range(args.concurrency)):
                    times.append(dt)
                    if code == 0 or code >= 500:
                        errors += 1
        summary[path] = {"p50": pct(times, 0.5), "p95": pct(times, 0.95),
                         "max": max(times) * 1000, "errors": errors, "n": len(times)}
        print(f"{path:30s} {summary[path]['p50']:8.0f} {summary[path]['p95']:8.0f} "
              f"{summary[path]['max']:8.0f} {errors:5d}")

    # 一致性检查：两处数据是否对得上
    print("\n一致性检查")
    _, alarms, _ = c.call("GET", "/alarms?limit=1")
    _, summary_body, _ = c.call("GET", "/reports/summary")
    alarm_total_api = alarms.get("total") if isinstance(alarms, dict) else None
    report_total = (summary_body.get("alarms") or {}).get("total") if isinstance(summary_body, dict) else None
    print(f"  告警列表 total={alarm_total_api} / 报表 total={report_total}"
          f" → {'一致' if alarm_total_api == report_total else '不一致（口径不同或时间窗不同）'}")

    _, devs, _ = c.call("GET", "/devices")
    _, runtime, _ = c.call("GET", "/robots/runtime")
    print(f"  设备数={len(devs) if isinstance(devs, list) else '?'} / 运行实例={len(runtime) if isinstance(runtime, list) else '?'}")

    _, h1, _ = c.call("GET", "/robots/1/status")
    _, h2, _ = c.call("GET", "/health/deep")
    if isinstance(h2, dict):
        print(f"  /health/deep.cache.online={h2.get('cache', {}).get('online')} "
              f"/ /robots/1/status.online={h1.get('online') if isinstance(h1, dict) else '?'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
