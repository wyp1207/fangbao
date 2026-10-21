"""录像：分段落盘 + 索引 + 回放。

设计取舍（单开发者、内网、浏览器要能直接放）：

- **不用数据库建索引**：录像文件本身就是索引。文件名带开始时间
  `{video_id}/{video_id}_20261021_153000.mp4`，列表靠扫描目录 + stat，
  删了文件列表就没了，不会出现"库里有、盘上没"的对不上。
- **转码成 H.264**：海康这两台是 HEVC，Chrome 放不了；`-c copy` 虽省 CPU
  但回放会黑屏。所以默认 libx264 veryfast，码率可控。
- **分片 5 分钟**：单文件损坏只丢一段；回放按段点播，浏览器 Range 直接拖。
- **同时录制上限 2 路**：1080p 转码很吃 CPU，超了直接拒绝而不是拖垮平台。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

ROOT = Path(os.environ.get("JC_RECORD_DIR", Path(__file__).resolve().parents[2] / "data" / "recordings"))
SEGMENT_SECONDS = int(os.environ.get("JC_RECORD_SEGMENT_SECONDS", "300"))
MAX_RECORDERS = 2
NAME_RE = re.compile(r"^(?P<vid>\d+)_(?P<ts>\d{8}_\d{6})\.mp4$")


class Recorder:
    def __init__(self, video_id: int, name: str) -> None:
        self.video_id = video_id
        self.name = name
        self.started_at = time.time()
        self._proc: subprocess.Popen | None = None
        self._dir = ROOT / str(video_id)
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, url: str) -> None:
        out = self._dir / f"{self.video_id}_%Y%m%d_%H%M%S.mp4"
        cmd = [
            FFMPEG, "-hide_banner", "-loglevel", "error",
            "-rtsp_transport", "tcp",
            "-i", url,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
            "-c:a", "aac", "-b:a", "64k",
            "-f", "segment", "-segment_time", str(SEGMENT_SECONDS),
            "-reset_timestamps", "1",
            "-strftime", "1", str(out),
        ]
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log.info("开始录像 video=%s -> %s", self.video_id, self._dir)

    def stop(self, timeout: float = 6.0) -> None:
        proc = self._proc
        if not proc:
            return
        if proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write(b"q")   # ffmpeg 收到 q 会正常收尾，写出 moov
                    proc.stdin.flush()
                proc.wait(timeout=timeout)
            except Exception:  # noqa: BLE001
                proc.kill()
        log.info("停止录像 video=%s", self.video_id)


class RecorderRegistry:
    def __init__(self) -> None:
        self._recorders: dict[int, Recorder] = {}
        self._lock = threading.Lock()

    def start(self, video_id: int, name: str, url: str) -> Recorder:
        from app.core.errors import BadRequest

        with self._lock:
            cur = self._recorders.get(video_id)
            if cur and cur.running:
                return cur
            if sum(1 for r in self._recorders.values() if r.running) >= MAX_RECORDERS:
                raise BadRequest(f"同时最多录制 {MAX_RECORDERS} 路，先停掉一路",
                                 code="RECORDER_BUSY")
            rec = Recorder(video_id, name)
            rec.start(url)
            self._recorders[video_id] = rec
            return rec

    def stop(self, video_id: int) -> None:
        with self._lock:
            rec = self._recorders.get(video_id)
            if rec:
                rec.stop()

    def status(self) -> list[dict]:
        with self._lock:
            return [
                {"video_id": vid, "name": r.name, "running": r.running,
                 "started_at": r.started_at}
                for vid, r in self._recorders.items()
            ]

    def stop_all(self) -> None:
        with self._lock:
            for rec in self._recorders.values():
                rec.stop()
            self._recorders.clear()


registry = RecorderRegistry()


# ---------- 文件索引 ----------

def segment_files(video_id: int | None = None) -> list[dict]:
    """扫描录像目录，返回分段列表（按开始时间倒序）。"""
    if not ROOT.exists():
        return []
    dirs = [ROOT / str(video_id)] if video_id else [d for d in ROOT.iterdir() if d.is_dir()]
    out: list[dict] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for f in d.glob("*.mp4"):
            m = NAME_RE.match(f.name)
            if not m:
                continue
            st = f.stat()
            try:
                started = datetime.strptime(m.group("ts"), "%Y%m%d_%H%M%S")
            except ValueError:
                continue
            out.append({
                "path": f"{d.name}/{f.name}",
                "video_id": int(d.name),
                "started_at": started.isoformat(timespec="seconds"),
                "size": st.st_size,
                "mtime": st.st_mtime,
            })
    out.sort(key=lambda x: x["started_at"], reverse=True)
    return out


def probe_duration(path: Path) -> float | None:
    if not FFPROBE or not path.exists():
        return None
    try:
        res = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=8,
        )
        return float(res.stdout.strip())
    except Exception:  # noqa: BLE001
        return None


# ---------- 保留策略（R1 按天数 / R2 按容量 / R5 磁盘保护）----------

def _cfg_int(name: str, default: int) -> int:
    try:
        from app.core.config import get_settings
        return int(getattr(get_settings(), name, default) or default)
    except Exception:  # noqa: BLE001
        return default


def purge(keep_days: int | None = None, max_gb: int | None = None) -> dict:
    """按保留策略删老录像。返回删了多少、为什么。

    顺序：先按天数删（R1），再看总量（R2）。两条都只删最老的，
    删到 70% 水位为止，不会一次把盘清空。
    """
    keep_days = keep_days if keep_days is not None else _cfg_int("record_keep_days", 30)
    max_gb = max_gb if max_gb is not None else _cfg_int("record_max_gb", 800)
    cutoff = time.time() - keep_days * 86400

    files = sorted(segment_files(), key=lambda f: f["started_at"])
    deleted = 0
    freed = 0
    for f in files:
        try:
            p = safe_path(f["path"])
        except Exception:  # noqa: BLE001
            continue
        mtime = p.stat().st_mtime
        if mtime < cutoff:
            size = p.stat().st_size
            p.unlink(missing_ok=True)
            deleted += 1
            freed += size
            continue
        break  # 已按时间升序，遇到未过期的就可以停

    total_bytes = sum(f["size"] for f in segment_files())
    cap = max_gb * 1024 ** 3
    if total_bytes > cap:
        target = int(cap * 0.7)
        for f in sorted(segment_files(), key=lambda x: x["started_at"]):
            if total_bytes <= target:
                break
            try:
                p = safe_path(f["path"])
                size = p.stat().st_size
                p.unlink(missing_ok=True)
                total_bytes -= size
                deleted += 1
                freed += size
            except Exception:  # noqa: BLE001
                continue

    return {"deleted": deleted, "freed_bytes": freed, "remaining_bytes": total_bytes}


def disk_free_gb() -> float:
    target = ROOT if ROOT.exists() else ROOT.parent
    try:
        return shutil.disk_usage(target).free / 1024 ** 3
    except Exception:  # noqa: BLE001
        return 999.0


class RetentionJanitor:
    """每 10 分钟跑一次；磁盘低于阈值时停掉所有录制（R5）。"""

    def __init__(self, interval_s: int = 600) -> None:
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
                res = purge()
                if res["deleted"]:
                    log.info("录像清理：删除 %s 个文件，释放 %.1f MB",
                             res["deleted"], res["freed_bytes"] / 1024 ** 2)
                min_free = _cfg_int("record_min_free_gb", 5)
                if disk_free_gb() < min_free:
                    log.warning("磁盘可用 %.1fGB 低于阈值 %sGB，停止所有录制", disk_free_gb(), min_free)
                    registry.stop_all()
                    from app.services.messages import store as msg_store
                    msg_store.add("danger", "system", "磁盘空间不足，已停止录像",
                                  f"可用 {disk_free_gb():.1f} GB < {min_free} GB", {"to": "record-plan"})
            except Exception:  # noqa: BLE001
                log.exception("录像清理失败")


janitor = RetentionJanitor()


def safe_path(rel: str) -> Path:
    """只允许取 ROOT 下的 mp4，防目录穿越。"""
    from app.core.errors import BadRequest

    if not rel.endswith(".mp4") or ".." in rel:
        raise BadRequest("非法路径", code="BAD_PATH")
    p = (ROOT / rel).resolve()
    if not str(p).startswith(str(ROOT.resolve())) or not p.exists():
        raise BadRequest("录像不存在", code="NOT_FOUND_FILE")
    return p
