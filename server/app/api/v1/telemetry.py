"""运行数据：采集、查询、清理。

采集：后台线程每 N 秒从轮询缓存取一份快照落库（不额外打机器人接口）。
查询：按时间范围做等间隔降采样，同时给统计（电量高低/均值、里程、速度峰值）。
清理：保留 7 天（可配），随 RetentionJanitor 一起跑。
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models.telemetry import TelemetrySample
from app.models.user import User
from sqlalchemy.orm import Session as _Session

log = logging.getLogger(__name__)
router = APIRouter(prefix="/telemetry", tags=["telemetry"])

SAMPLE_INTERVAL_S = 10
KEEP_DAYS = 7


class TelemetryCollector:
    def __init__(self, cache_getter: Callable[[], Any], session_factory: Callable[[], _Session],
                 interval_s: int = SAMPLE_INTERVAL_S) -> None:
        self._cache = cache_getter
        self._session_factory = session_factory
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self._sample_once()
            except Exception:  # noqa: BLE001 - 采样失败不能影响主流程
                log.exception("运行数据采样失败")

    def _sample_once(self) -> None:
        raw = self._cache()
        if raw is None:
            return
        # 支持单台（snapshot）和多台（[(robot_id, snapshot)]）两种取数方式
        pairs = raw if isinstance(raw, list) else [(1, raw)]
        for robot_id, snap in pairs:
            if snap is not None:
                self._sample_one(robot_id, snap)

    def _sample_one(self, robot_id: int, snap) -> None:
        info = getattr(snap, "info", {}) or {}
        pose = getattr(snap, "pose", {}) or {}
        status = getattr(snap, "status", {}) or {}
        galileo = getattr(snap, "galileo", {}) or {}
        age = getattr(snap, "age_s", None)

        # 字段来源各型号不一样，按优先级兜底（JCROB：电量在 info，电压/速度在 galileo）
        row = TelemetrySample(
            robot_id=robot_id,
            battery=_num(info.get("battery")),
            voltage=_num(galileo.get("power")) or _num(info.get("voltage")) or _num(status.get("voltage")),
            speed=_num(galileo.get("currentSpeedX")) or _num(status.get("speed_x")) or _num(info.get("speed")),
            yaw_rate=_num(galileo.get("currentSpeedTheta")) or _num(status.get("speed_angle")),
            x=_num(pose.get("x")), y=_num(pose.get("y")), theta=_num(pose.get("theta_rad")),
            online=bool(age is not None and age < 10),
            estop=bool(info.get("driver_port") is True),
        )
        with self._session_factory() as db:  # type: ignore[misc]
            db.add(row)
            db.commit()


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)) and not math.isnan(v):
        return float(v)
    return None


def rollup(session_factory: Callable[[], _Session], hours: int = 26) -> int:
    """把最近 N 小时的原始采样聚合成分钟桶（幂等：同分钟先删后插）。

    报表查长区间时读聚合表，避免扫 10s 原始数据（1 天 8640 行/台）。
    """
    from collections import defaultdict

    from sqlalchemy import func

    from app.models.telemetry import TelemetryRollup, TelemetrySample

    end = datetime.now().replace(second=0, microsecond=0)
    start = end - timedelta(hours=hours)
    written = 0
    with session_factory() as db:  # type: ignore[misc]
        rows = db.scalars(select(TelemetrySample).where(
            TelemetrySample.ts >= start, TelemetrySample.ts < end)).all()
        buckets: dict[tuple, list] = defaultdict(list)
        for r in rows:
            key = (r.ts.replace(second=0, microsecond=0), r.robot_id or 0)
            buckets[key].append(r)

        for (bucket, rid), items in buckets.items():
            db.query(TelemetryRollup).filter(
                TelemetryRollup.bucket == bucket,
                TelemetryRollup.robot_id == rid,
            ).delete(synchronize_session=False)
            batteries = [i.battery for i in items if i.battery is not None]
            speeds = [i.speed for i in items if i.speed is not None]
            db.add(TelemetryRollup(
                bucket=bucket, robot_id=rid, samples=len(items),
                battery_avg=round(sum(batteries) / len(batteries), 2) if batteries else None,
                battery_min=min(batteries) if batteries else None,
                speed_avg=round(sum(speeds) / len(speeds), 2) if speeds else None,
                online_ratio=round(sum(1 for i in items if i.online) / len(items), 3),
            ))
            written += 1
        db.commit()
    return written


def purge(session_factory: Callable[[], _Session], keep_days: int = KEEP_DAYS) -> int:
    cutoff = datetime.now() - timedelta(days=keep_days)
    with session_factory() as db:  # type: ignore[misc]
        res = db.execute(delete(TelemetrySample).where(TelemetrySample.ts < cutoff))
        db.commit()
        return res.rowcount or 0


@router.get("/rollup")
def query_rollup(
    hours: int = Query(180 * 24, ge=1, le=24 * 365),
    robot_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """分钟级聚合（保留 180 天），长区间报表用这个。"""
    from app.models.telemetry import TelemetryRollup

    start = datetime.now() - timedelta(hours=hours)
    q = select(TelemetryRollup).where(TelemetryRollup.bucket >= start)
    if robot_id is not None:
        q = q.where(TelemetryRollup.robot_id == robot_id)
    rows = db.scalars(q.order_by(TelemetryRollup.bucket)).all()
    return {"rows": [
        {"bucket": r.bucket.isoformat(timespec="minutes"), "robot_id": r.robot_id,
         "samples": r.samples, "battery_avg": r.battery_avg, "battery_min": r.battery_min,
         "speed_avg": r.speed_avg, "online_ratio": r.online_ratio}
        for r in rows
    ]}


@router.get("/poses")
def query_poses(
    hours: int = Query(24, ge=1, le=24 * 14),
    points: int = Query(1200, ge=50, le=5000),
    robot_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """历史位姿（给 3D 轨迹回放用）。按时间升序、跳变过滤、等间隔抽稀。"""
    since = datetime.now() - timedelta(hours=hours)
    conds = [TelemetrySample.ts >= since, TelemetrySample.x.isnot(None),
             TelemetrySample.y.isnot(None)]
    if robot_id is not None:
        conds.append(TelemetrySample.robot_id == robot_id)
    rows = db.scalars(
        select(TelemetrySample).where(*conds).order_by(TelemetrySample.ts)
    ).all()
    if not rows:
        return {"count": 0, "points": [], "hours": hours, "distance_m": 0.0,
                "from": None, "to": None}

    # 过滤定位跳变（>5m 认为是一次重定位，不画连线）
    clean: list[TelemetrySample] = []
    prev = None
    for r in rows:
        if prev is not None and math.hypot(r.x - prev.x, r.y - prev.y) > 5:
            clean.append(None)  # type: ignore[arg-type]  # 断点
        clean.append(r)
        prev = r

    step = max(1, len(clean) // points)
    sampled = clean[::step]
    out = []
    distance = 0.0
    last = None
    for r in sampled:
        if r is None:
            last = None
            continue
        if last is not None:
            distance += math.hypot(r.x - last.x, r.y - last.y)
        last = r
        out.append({"ts": r.ts.isoformat(timespec="seconds"),
                    "x": round(r.x, 3), "y": round(r.y, 3),
                    "theta": round(r.theta or 0.0, 3)})
    return {
        "count": len(out), "hours": hours, "points": out,
        "distance_m": round(distance, 1),
        "from": out[0]["ts"] if out else None,
        "to": out[-1]["ts"] if out else None,
    }


@router.get("")
def query_telemetry(
    hours: int = Query(24, ge=1, le=24 * 14),
    points: int = Query(180, ge=10, le=1000),
    robot_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    since = datetime.now() - timedelta(hours=hours)
    conds = [TelemetrySample.ts >= since]
    if robot_id is not None:
        conds.append(TelemetrySample.robot_id == robot_id)
    rows = db.scalars(
        select(TelemetrySample).where(*conds).order_by(TelemetrySample.ts)
    ).all()
    if not rows:
        return {"count": 0, "series": [], "stats": None, "hours": hours}

    span = (rows[-1].ts - rows[0].ts).total_seconds() or 1
    bucket = max(span / points, 1.0)
    buckets: dict[int, list[TelemetrySample]] = {}
    for r in rows:
        buckets.setdefault(int((r.ts - rows[0].ts).total_seconds() // bucket), []).append(r)

    series = []
    for idx in sorted(buckets):
        group = buckets[idx]
        series.append({
            "ts": (rows[0].ts + timedelta(seconds=idx * bucket)).isoformat(timespec="seconds"),
            "battery": _avg([g.battery for g in group]),
            "speed": _avg([g.speed for g in group]),
            "voltage": _avg([g.voltage for g in group]),
            "online": any(g.online for g in group),
        })

    batteries = [r.battery for r in rows if r.battery is not None]
    speeds = [r.speed for r in rows if r.speed is not None]
    distance = 0.0
    prev = None
    for r in rows:
        if r.x is None or r.y is None:
            prev = None
            continue
        if prev is not None:
            d = math.hypot(r.x - prev[0], r.y - prev[1])
            if d < 5:  # 过滤定位跳变
                distance += d
        prev = (r.x, r.y)

    offline_samples = sum(1 for r in rows if not r.online)
    return {
        "count": len(rows),
        "hours": hours,
        "series": series,
        "stats": {
            "battery_min": round(min(batteries), 1) if batteries else None,
            "battery_max": round(max(batteries), 1) if batteries else None,
            "battery_avg": round(sum(batteries) / len(batteries), 1) if batteries else None,
            "speed_max": round(max(speeds), 2) if speeds else None,
            "distance_m": round(distance, 1),
            "offline_ratio": round(offline_samples / len(rows) * 100, 1),
            "from": rows[0].ts.isoformat(timespec="seconds"),
            "to": rows[-1].ts.isoformat(timespec="seconds"),
        },
    }


def _avg(values: list[float | None]) -> float | None:
    xs = [v for v in values if v is not None]
    return round(sum(xs) / len(xs), 2) if xs else None
