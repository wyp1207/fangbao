"""Prometheus 文本格式的 /metrics（标准库，无新依赖）。

工业现场最先问的一句话是"平台自己挂了谁告诉你"。有探针不等于有度量：
这里给最小可用的四个东西——请求量/错误数/耗时、设备在线数、轮询数据年龄、库大小。
抓取方式：Prometheus 直接抓 /metrics；没配 token 时只允许内网访问。
"""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import APIRouter, Request, Response

from app.core.config import get_settings

router = APIRouter(tags=["ops"])

STARTED = time.time()
_requests: dict[tuple[str, str], int] = defaultdict(int)
_latency_sum: dict[str, float] = defaultdict(float)
_errors = 0


def record(method: str, path: str, status: int, seconds: float) -> None:
    """由中间件调用：按 method/status 类聚合，避免高基数。"""
    global _errors
    bucket = f"{method} {path.split('?', 1)[0]}"
    _requests[(bucket, f"{status // 100}xx")] += 1
    _latency_sum[bucket] += seconds
    if status >= 500:
        _errors += 1


def _allowed(request: Request) -> bool:
    token = get_settings().metrics_token
    if token:
        return request.headers.get("x-metrics-token") == token
    host = (request.client.host if request.client else "") or ""
    return host.startswith(("127.", "10.", "192.168.", "172.16.", "172.17.",
                            "172.18.", "172.19.", "172.2", "172.30.", "172.31."))


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    if not _allowed(request):
        return Response("forbidden\n", status_code=403, media_type="text/plain")

    lines: list[str] = ["# HELP jc_uptime_seconds 进程运行时长", "# TYPE jc_uptime_seconds gauge",
                        f"jc_uptime_seconds {time.time() - STARTED:.1f}"]

    lines += ["# HELP jc_http_requests_total 按方法与状态类统计的请求数",
              "# TYPE jc_http_requests_total counter"]
    for (bucket, status_cls), n in sorted(_requests.items()):
        method, path = bucket.split(" ", 1)
        lines.append(f'jc_http_requests_total{{method="{method}",path="{path}",status="{status_cls}"}} {n}')

    lines += ["# HELP jc_http_5xx_total 5xx 总数", "# TYPE jc_http_5xx_total counter",
              f"jc_http_5xx_total {_errors}"]

    lines += ["# HELP jc_http_latency_seconds_sum 累计耗时", "# TYPE jc_http_latency_seconds_sum counter"]
    for bucket, total in sorted(_latency_sum.items()):
        method, path = bucket.split(" ", 1)
        lines.append(f'jc_http_latency_seconds_sum{{method="{method}",path="{path}"}} {total:.3f}')

    # 设备侧：在线数 + 数据年龄（离线/卡顿时这两个数会变）
    try:
        from app.services import robot_runtime as rr

        registry = rr.get_registry() if hasattr(rr, "get_registry") else None
    except Exception:  # noqa: BLE001
        registry = None
    if registry is not None:
        runtimes = getattr(registry, "all", lambda: [])()
        online = sum(1 for r in runtimes if r.cache.online)
        lines += ["# HELP jc_devices_total 接入设备数", "# TYPE jc_devices_total gauge",
                  f"jc_devices_total {len(runtimes)}",
                  "# HELP jc_devices_online 在线设备数", "# TYPE jc_devices_online gauge",
                  f"jc_devices_online {online}"]
        for r in runtimes:
            age = r.cache.as_dict()["age_s"]
            lines.append(f'jc_device_data_age_seconds{{robot="{r.robot_id}"}} {age:.1f}')
    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
