"""视频源管理。

要点：
- RTSP 里的密码永远不出服务端：出参统一打码，前端提交打码串时保留原密码。
- 不在这里做转流。浏览器放不了 RTSP，实际播放要经 MediaMTX/ffmpeg 转 HLS 或 WebRTC；
  `play_url` 只在配置了 `video_hls_base` 时才返回可播地址，否则明确告诉前端「没有转流服务」。
- 「测试」只做 TCP 连通性检查（host:port 能不能连上），不解析 RTSP 协议，避免引依赖。
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_csrf, require_roles
from app.core.config import get_settings
from app.core.errors import BadRequest, NotFound
from app.db.session import get_db
from app.models.user import User
from app.models.video_source import VideoSource

router = APIRouter(prefix="/videos", tags=["videos"])

# 抓帧缓存：id -> (时间戳, jpeg bytes)。摄像头多路时避免每次刷新都拉一遍流。
_SNAP_CACHE: dict[int, tuple[float, bytes]] = {}
_SNAP_TTL = 2.0
_FFMPEG = shutil.which("ffmpeg")

VENDORS = {"hikvision": "海康", "dahua": "大华", "other": "其他"}

_USERINFO = re.compile(r"(?P<scheme>\w+://)(?P<user>[^:/@]*):(?P<pwd>[^@/]*)@")


def mask_url(url: str) -> str:
    return _USERINFO.sub(lambda m: f"{m.group('scheme')}{m.group('user')}:***@", url)


def split_url(url: str) -> tuple[str, int]:
    parts = urlsplit(url)
    if not parts.hostname:
        raise BadRequest("视频流地址不合法，缺少主机", code="BAD_URL")
    port = parts.port or (554 if parts.scheme.startswith("rtsp") else 80)
    return parts.hostname, port


class VideoOut(BaseModel):
    id: int
    name: str
    group_name: str
    vendor: str
    url: str          # 已打码
    enabled: bool
    note: str | None = None
    play_url: str | None = None


class VideoIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    group_name: str = Field(default="默认分组", max_length=32)
    vendor: str = "other"
    url: str = Field(min_length=4, max_length=512)
    enabled: bool = True
    note: str | None = Field(default=None, max_length=200)


class VideoPatch(BaseModel):
    name: str | None = None
    group_name: str | None = None
    vendor: str | None = None
    url: str | None = None
    enabled: bool | None = None
    note: str | None = None


def _play_url(name: str) -> str | None:
    """只有配了转流服务前缀才给可播地址，避免前端拿到一个放不了的链接。"""
    base = getattr(get_settings(), "video_hls_base", "") or ""
    if not base:
        return None
    return f"{base.rstrip('/')}/{name}.m3u8"


def _out(v: VideoSource) -> VideoOut:
    return VideoOut(
        id=v.id, name=v.name, group_name=v.group_name, vendor=v.vendor,
        url=mask_url(v.url), enabled=v.enabled, note=v.note,
        play_url=_play_url(v.name) if v.enabled else None,
    )


@router.get("", response_model=list[VideoOut])
def list_videos(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator", "viewer")),
) -> list[VideoOut]:
    rows = db.scalars(select(VideoSource).order_by(VideoSource.id)).all()
    return [_out(v) for v in rows]


@router.post("", response_model=VideoOut, dependencies=[Depends(require_csrf)])
def create_video(
    body: VideoIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> VideoOut:
    if body.vendor not in VENDORS:
        raise BadRequest("厂商只能是 hikvision/dahua/other", code="BAD_VENDOR")
    split_url(body.url)  # 提前校验
    v = VideoSource(**body.model_dump())
    db.add(v)
    db.commit()
    db.refresh(v)
    return _out(v)


@router.patch("/{video_id}", response_model=VideoOut, dependencies=[Depends(require_csrf)])
def update_video(
    video_id: int,
    body: VideoPatch,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> VideoOut:
    v = db.get(VideoSource, video_id)
    if not v:
        raise NotFound("视频源不存在")
    data = body.model_dump(exclude_none=True)
    if "vendor" in data and data["vendor"] not in VENDORS:
        raise BadRequest("厂商只能是 hikvision/dahua/other", code="BAD_VENDOR")
    if "url" in data:
        # 前端提交打码串 = 没改地址，保留原值
        data["url"] = v.url if "***@" in data["url"] else data["url"]
        split_url(data["url"])
    for k, val in data.items():
        setattr(v, k, val)
    db.commit()
    db.refresh(v)
    return _out(v)


@router.post("/{video_id}/test", dependencies=[Depends(require_csrf)])
def test_video(
    video_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
) -> dict:
    v = db.get(VideoSource, video_id)
    if not v:
        raise NotFound("视频源不存在")
    host, port = split_url(v.url)
    try:
        with socket.create_connection((host, port), timeout=3):
            return {"ok": True, "target": f"{host}:{port}", "message": f"端口 {port} 可连通"}
    except OSError as exc:
        return {"ok": False, "target": f"{host}:{port}", "message": f"连不上：{exc.__class__.__name__}"}


@router.get("/{video_id}/snapshot")
def snapshot(
    video_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator", "viewer")),
):
    """用 ffmpeg 抓一帧 JPEG。

    浏览器放不了 RTSP，但「每 2 秒抓一帧」足够看清现场在干什么，
    也不用为了预览单独部署转流服务。要真正流畅视频再上 MediaMTX。
    """
    from fastapi import Response
    from app.core.errors import ExternalUnavailable

    if not _FFMPEG:
        raise ExternalUnavailable("服务端没有 ffmpeg，无法抓帧", code="FFMPEG_MISSING")

    v = db.get(VideoSource, video_id)
    if not v:
        raise NotFound("视频源不存在")

    hit = _SNAP_CACHE.get(video_id)
    if hit and time.time() - hit[0] < _SNAP_TTL:
        return Response(content=hit[1], media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})

    cmd = [
        _FFMPEG, "-hide_banner", "-loglevel", "error",
        "-rtsp_transport", "tcp", "-timeout", "5000000",
        "-i", v.url, "-frames:v", "1", "-f", "image2", "-vcodec", "mjpeg", "-q:v", "6", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=8)
    except subprocess.TimeoutExpired:
        raise ExternalUnavailable("抓帧超时，检查摄像头是否在线", code="SNAPSHOT_TIMEOUT")
    if proc.returncode != 0 or not proc.stdout:
        # 错误信息里可能带完整 URL（含密码），这里只回固定文案
        raise ExternalUnavailable("抓帧失败，检查地址/账号/网络", code="SNAPSHOT_FAILED")

    _SNAP_CACHE[video_id] = (time.time(), proc.stdout)
    return Response(content=proc.stdout, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


@router.delete("/{video_id}", dependencies=[Depends(require_csrf)])
def delete_video(
    video_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> dict:
    v = db.get(VideoSource, video_id)
    if not v:
        raise NotFound("视频源不存在")
    db.delete(v)
    db.commit()
    return {"ok": True}
