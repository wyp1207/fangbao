"""到点抓拍：从 go2rtc 取一帧存成证据图。

为什么用 go2rtc 抓帧而不是等机器人厂商的抓拍 API：
现场相机已经接进 go2rtc 了（实时预览在用），抓帧是同一路流；
厂商抓拍接口还没确认，先用这条把"到点有照片"的证据链补上，
将来接上厂商接口只是换实现，调用方不动。
"""

from __future__ import annotations

import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from uuid import uuid4

PHOTO_ROOT = Path(__file__).resolve().parents[3] / "data" / "inspection_photos"


def capture_frame(stream: str, base: str, timeout: float = 6.0) -> dict:
    """抓一帧并落盘，返回 {path, url, bytes}。失败抛 RuntimeError。"""
    if not stream:
        raise RuntimeError("没有可用的视频流")
    q = urllib.parse.urlencode({"src": stream})
    url = f"{base.rstrip('/')}/api/frame.jpeg?{q}"
    data = b""
    last = ""
    # 流没消费者时 go2rtc 可能还没出帧：重试几次，第一次往往拿到空
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                data = resp.read()
        except Exception as exc:  # noqa: BLE001
            last = f"{exc.__class__.__name__}"
            data = b""
        if len(data) >= 1024:
            break
        last = f"{len(data)}B"
        time.sleep(0.6)
    if len(data) < 1024:
        raise RuntimeError(f"抓帧失败（{stream}）：{last}，可能是黑帧或流未就绪")

    day = datetime.now().strftime("%Y%m%d")
    name = f"shot-{day}/{int(time.time())}-{uuid4().hex[:8]}.jpg"
    (PHOTO_ROOT / f"shot-{day}").mkdir(parents=True, exist_ok=True)
    (PHOTO_ROOT / name).write_bytes(data)
    return {
        "path": f"inspection_photos/{name}",
        "url": f"/api/v1/inspection/photos/{name}",
        "bytes": len(data),
        "stream": stream,
    }


def save_photo_bytes(data: bytes, source: str = "sdk") -> dict:
    """把已经拿到的 JPEG 字节落盘（SDK 抓拍用，不用再走 go2rtc）。"""
    if len(data) < 1024:
        raise RuntimeError(f"抓拍内容过小（{len(data)}B）")
    day = datetime.now().strftime("%Y%m%d")
    name = f"shot-{day}/{int(time.time())}-{uuid4().hex[:8]}.jpg"
    (PHOTO_ROOT / f"shot-{day}").mkdir(parents=True, exist_ok=True)
    (PHOTO_ROOT / name).write_bytes(data)
    return {
        "path": f"inspection_photos/{name}",
        "url": f"/api/v1/inspection/photos/{name}",
        "bytes": len(data),
        "source": source,
    }


def probe_direct(url: str, timeout: float = 6.0) -> tuple[bool, str]:
    """绕过中继，直接连相机 RTSP 抓一帧（判断"相机本身通不通"）。

    为什么需要：探活以前只走 go2rtc，导致中继一挂就误判"视频不可用"，
    实际上 ffmpeg 直连相机是好的。这里给健康检查一条不依赖中继的路。
    """
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False, "服务端没有 ffmpeg"
    if not url:
        return False, "没有视频地址"
    cmd = [ffmpeg, "-v", "error", "-rtsp_transport", "tcp", "-i", url,
           "-frames:v", "1", "-f", "image2", "-vcodec", "mjpeg", "-q:v", "6", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return False, "直连相机超时"
    if len(proc.stdout) >= 1024:
        return True, f"直连 {len(proc.stdout)}B"
    err = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
    return False, (err[-1][:120] if err else "直连无画面")


def probe_frame(stream: str, base: str, timeout: float = 2.5) -> tuple[bool, str]:
    """只探测流是否出帧，不落盘（首页用它决定显示视频还是"未接入"）。"""
    if not stream or not base:
        return False, "未配置视频流"
    q = urllib.parse.urlencode({"src": stream})
    url = f"{base.rstrip('/')}/api/frame.jpeg?{q}"
    last = ""
    data = b""
    for _ in range(2):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                data = resp.read()
        except Exception as exc:  # noqa: BLE001
            last = exc.__class__.__name__
            data = b""
        if len(data) >= 1024:
            break
    if not data:
        return False, last or "无响应"
    if len(data) < 1024:
        return False, "相机无画面（0 字节）"
    return True, f"{len(data)}B"
