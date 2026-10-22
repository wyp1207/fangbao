"""磁盘监控：数据盘和数据库盘分开看。

为什么要分开：录像写满数据盘是"业务降级"，数据库盘写满直接"整站 500"，
两者的严重程度完全不同，不能合并成一个阈值。

行为：
- 每 5 分钟检查一次
- 低于提醒阈值（默认 20GB）→ 发一条消息，不进告警（避免每天刷）
- 低于严重阈值（默认 8GB）→ 产生 critical 告警（走同一套确认/外发）
- 录像另有 5GB 硬停阈值（在 recorder 的 RetentionJanitor 里）
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)


def _free_gb(path: Path) -> dict:
    try:
        usage = shutil.disk_usage(path if path.exists() else path.parent)
        return {
            "path": str(path),
            "free_gb": round(usage.free / 1024 ** 3, 1),
            "total_gb": round(usage.total / 1024 ** 3, 1),
            "used_pct": round(usage.used / usage.total * 100, 1) if usage.total else 0,
        }
    except Exception as exc:  # noqa: BLE001
        return {"path": str(path), "free_gb": None, "total_gb": None, "used_pct": None,
                "error": exc.__class__.__name__}


def snapshot() -> dict:
    """给 /health/deep 和系统设置页用。"""
    from app.services.recorder import ROOT as REC_ROOT

    data_dir = REC_ROOT.parent if REC_ROOT.parent.exists() else Path("/")
    db_dir = Path(__file__).resolve().parents[2] / "data"
    return {
        "data": _free_gb(data_dir),
        "database": _free_gb(db_dir),
    }


class DiskMonitor:
    def __init__(self, interval_s: int = 300) -> None:
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._alarms = None

    def attach(self, alarms) -> None:
        """由 main 注入 AlarmStore（磁盘告警走同一套确认/外发）。"""
        self._alarms = alarms

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # 启动先等 30 秒，别和迁移/首次轮询抢资源
        if self._stop.wait(30):
            return
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception:  # noqa: BLE001
                log.exception("磁盘检查失败")
            if self._stop.wait(self.interval_s):
                break

    def check_once(self) -> dict:
        from app.api.v1.settings import load_all
        from app.services.messages import store as msg_store

        cfg = load_all()
        warn_gb = int(cfg.get("disk.warn_free_gb", 20))
        crit_gb = int(cfg.get("disk.crit_free_gb", 8))

        snap = snapshot()
        results: dict[str, str] = {}

        for name, info in snap.items():
            free = info.get("free_gb")
            if free is None:
                continue
            label = "录像数据盘" if name == "data" else "数据库盘"

            if free < crit_gb:
                results[name] = "critical"
                self._raise(label, "critical", f"{label}可用空间仅 {free} GB（阈值 {crit_gb} GB），"
                                              f"目录 {info['path']}")
            elif free < warn_gb:
                results[name] = "warn"
                # 提醒只发消息，不进告警中心，避免每天一条
                msg_store.add("warn", "system", f"{label}空间偏低：{free} GB",
                              f"低于提醒阈值 {warn_gb} GB，目录 {info['path']}，请清理或扩容",
                              {"to": "settings"})
            else:
                results[name] = "ok"
        return results

    def _raise(self, label: str, level: str, message: str) -> None:
        if self._alarms is None:
            log.warning("磁盘告警（未注入 AlarmStore）：%s", message)
            return
        self._alarms.raise_external(metric="disk_space", level=level, message=message)


monitor = DiskMonitor()
