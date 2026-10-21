"""视频流共享管理。

问题：每个浏览器观众都起一条 ffmpeg → 相机会被开多条 RTSP 会话，进程也泄漏。

做法（和 detask 里 go2rtc 的角色一样）：
- 每路摄像头只起 **一个** ffmpeg，持续把 RTSP 转成 JPEG 帧；
- 后台线程解析帧，缓存「最新一帧」；
- /mjpeg 的每个观众只是从缓存里按帧率取最新帧，不再碰 ffmpeg 和摄像头；
- 没有观众超过 idle 秒数就自动杀掉 ffmpeg，不占 CPU。

这样首帧只付一次握手成本，之后所有观众共享，延迟由取帧节奏决定。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time

log = logging.getLogger(__name__)

FFMPEG = shutil.which("ffmpeg")
FPS = 8


def _scale_width() -> int:
    try:
        from app.core.config import get_settings
        return int(getattr(get_settings(), "video_scale_width", 1280) or 1280)
    except Exception:
        return 1280


SCALE_WIDTH = _scale_width()
IDLE_SECONDS = 20.0
SOI = b"\xff\xd8"
EOI = b"\xff\xd9"


class VideoStream:
    def __init__(self, video_id: int, url: str) -> None:
        self.video_id = video_id
        self.url = url
        self.latest: bytes | None = None
        self.latest_ts = 0.0
        self.viewers = 0
        self.last_used = time.time()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._reader: threading.Thread | None = None

    # ---- 生命周期 ----
    def start(self) -> None:
        cmd = [
            FFMPEG, "-hide_banner", "-loglevel", "error",
            "-rtsp_transport", "tcp",
            "-fflags", "nobuffer", "-flags", "low_delay",
            "-probesize", "32768", "-analyzeduration", "0",
            "-i", self.url,
            "-an", "-vf", f"fps={FPS},scale={SCALE_WIDTH}:-2",
            "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "7", "-",
        ]
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
        )
        self._stop.clear()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        log.info("视频流转码启动 video=%s", self.video_id)

    def stop(self) -> None:
        self._stop.set()
        proc = self._proc
        if proc and proc.poll() is None:
            proc.kill()
        if self._reader and self._reader.is_alive():
            self._reader.join(timeout=2)

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ---- 读帧 ----
    def _read_loop(self) -> None:
        buf = b""
        assert self._proc and self._proc.stdout
        while not self._stop.is_set():
            chunk = self._proc.stdout.read(32768)
            if not chunk:
                break
            buf += chunk
            while True:
                start = buf.find(SOI)
                if start < 0:
                    buf = b""
                    break
                end = buf.find(EOI, start + 2)
                if end < 0:
                    buf = buf[start:]
                    break
                frame = buf[start:end + 2]
                buf = buf[end + 2:]
                with self._lock:
                    self.latest = frame
                    self.latest_ts = time.time()

    def frame(self) -> bytes | None:
        with self._lock:
            return self.latest


class StreamRegistry:
    def __init__(self) -> None:
        self._streams: dict[int, VideoStream] = {}
        self._lock = threading.Lock()
        self._janitor: threading.Thread | None = None

    def acquire(self, video_id: int, url: str) -> VideoStream:
        with self._lock:
            stream = self._streams.get(video_id)
            if stream is None or not stream.running:
                stream = VideoStream(video_id, url)
                stream.start()
                self._streams[video_id] = stream
            stream.viewers += 1
            stream.last_used = time.time()
        self._ensure_janitor()
        return stream

    def release(self, video_id: int) -> None:
        with self._lock:
            stream = self._streams.get(video_id)
            if stream:
                stream.viewers = max(0, stream.viewers - 1)
                stream.last_used = time.time()

    def reset(self) -> None:
        with self._lock:
            for s in self._streams.values():
                s.stop()
            self._streams.clear()

    # ---- 空闲回收 ----
    def _ensure_janitor(self) -> None:
        if self._janitor and self._janitor.is_alive():
            return
        self._janitor = threading.Thread(target=self._loop, daemon=True)
        self._janitor.start()

    def _loop(self) -> None:
        while True:
            time.sleep(5)
            now = time.time()
            with self._lock:
                # 以「最后一次真正取到帧」为准：浏览器断开时 finally 不一定及时跑，
                # 只看 viewers 会永远回收不掉。
                dead = [
                    vid for vid, s in self._streams.items()
                    if now - s.last_used > IDLE_SECONDS
                ]
                for vid in dead:
                    self._streams.pop(vid).stop()
                    log.info("视频流空闲回收 video=%s", vid)

    def stats(self) -> list[dict]:
        with self._lock:
            return [
                {"video_id": vid, "viewers": s.viewers, "running": s.running,
                 "age_s": round(time.time() - s.latest_ts, 1) if s.latest_ts else None}
                for vid, s in self._streams.items()
            ]


registry = StreamRegistry()
