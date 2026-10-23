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

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_csrf, require_roles
from app.core.config import get_settings
from app.core.errors import BadRequest, NotFound
from app.db.session import get_db
from app.models.user import User
from app.models.video_source import VideoSource
from app.services.messages import audit

router = APIRouter(prefix="/videos", tags=["videos"])

# 抓帧缓存：id -> (时间戳, jpeg bytes)。摄像头多路时避免每次刷新都拉一遍流。
_SNAP_CACHE: dict[int, tuple[float, bytes]] = {}
_SNAP_TTL = 2.0
_FFMPEG = shutil.which("ffmpeg")
def _alive(video_id: int) -> list[subprocess.Popen]:
    procs = _streams.get(video_id, [])
    alive = [p for p in procs if p.poll() is None]
    _streams[video_id] = alive
    return alive


def _total_alive() -> int:
    return sum(len(_alive(vid)) for vid in list(_streams))


def _upstream(url: str) -> str:
    """优先走中继（go2rtc / MediaMTX），复用同一条上游流。

    直连相机时每个观看者都会新开一条 RTSP 会话，相机侧连接数有限；
    有中继就只连中继一次，和 detask 的做法一致。
    """
    relay = getattr(get_settings(), "video_relay_url", "") or ""
    return relay.rstrip("/") + "/" + url.split("/")[-1] if relay else url

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
    show_on_dashboard: bool = False
    note: str | None = None
    stream_name: str = ""
    play_url: str | None = None
    go2rtc_url: str | None = None   # go2rtc 播放页（MSE ~0.5s），浏览器 iframe 直接放


class VideoIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    group_name: str = Field(default="默认分组", max_length=32)
    vendor: str = "other"
    url: str = Field(min_length=4, max_length=512)
    enabled: bool = True
    show_on_dashboard: bool = False
    note: str | None = Field(default=None, max_length=200)
    stream_name: str = Field(default="", max_length=32)


class VideoPatch(BaseModel):
    name: str | None = None
    group_name: str | None = None
    vendor: str | None = None
    url: str | None = None
    enabled: bool | None = None
    show_on_dashboard: bool | None = None
    note: str | None = None
    stream_name: str | None = None


def _play_url(name: str) -> str | None:
    """只有配了转流服务前缀才给可播地址，避免前端拿到一个放不了的链接。"""
    base = getattr(get_settings(), "video_hls_base", "") or ""
    if not base:
        return None
    return f"{base.rstrip('/')}/{name}.m3u8"


def _rtsp_for_stream(stream: str, base: str) -> str:
    """从 go2rtc 反查这路流的 RTSP 源，保证截图/转码和"选中的流"是同一个画面。

    没有 go2rtc 或查不到就返回空串，调用方回落到数据库里的 url。
    """
    import json as _json
    import urllib.request as _req

    if not base or not stream:
        return ""
    name = stream[:-4] if stream.endswith("_web") else stream
    try:
        with _req.urlopen(f"{base.rstrip('/')}/api/streams", timeout=2.5) as r:
            data = _json.loads(r.read().decode("utf-8", "replace"))
        prod = ((data.get(name) or {}).get("producers") or [{}])[0]
        url = prod.get("url") or ""
        if url.startswith("ffmpeg:") or not url.startswith("rtsp"):
            # ffmpeg:xxx 是指向另一路流的别名，顺着找一层
            alias = url.split(":", 1)[1].split("#")[0] if url.startswith("ffmpeg:") else ""
            prod2 = ((data.get(alias) or {}).get("producers") or [{}])[0]
            url = prod2.get("url") or ""
        return url if url.startswith("rtsp") else ""
    except Exception:  # noqa: BLE001
        return ""


_WEB_CACHE: dict[str, tuple[bool, float]] = {}


def _has_web_variant(stream: str, base: str) -> bool:
    """go2rtc 里有没有 <stream>_web（H265→H264 的转码变体）。结果缓存 60 秒。"""
    import json as _json
    import time as _time
    import urllib.request as _req

    key = f"{base}|{stream}"
    hit = _WEB_CACHE.get(key)
    if hit and _time.time() - hit[1] < 60:
        return hit[0]
    ok = False
    try:
        with _req.urlopen(f"{base.rstrip('/')}/api/streams", timeout=2.5) as r:
            names = set(_json.loads(r.read().decode("utf-8", "replace")))
        ok = f"{stream}_web" in names
    except Exception:  # noqa: BLE001
        ok = False
    _WEB_CACHE[key] = (ok, _time.time())
    return ok


def _go2rtc_url(stream_name: str) -> str | None:
    settings = get_settings()
    if not stream_name:
        return None
    # 部署时优先用同源反代前缀（nginx /go2rtc/），开发时回落到直连地址
    base = getattr(settings, "go2rtc_public_base", "") or getattr(settings, "go2rtc_base", "") or ""
    if not base:
        return None
    # 和 detask(8123) 一致：H265 相机走 _web 变体（约 0.5s 延迟、每路约 0.3 核）
    name = f"{stream_name}_web" if _has_web_variant(stream_name, base) else stream_name
    mode = getattr(get_settings(), "video_play_mode", "webrtc") or "webrtc"
    return f"{base.rstrip('/')}/stream.html?src={name}&mode={mode}"


def _out(v: VideoSource) -> VideoOut:
    return VideoOut(
        id=v.id, name=v.name, group_name=v.group_name, vendor=v.vendor,
        url=mask_url(v.url), enabled=v.enabled,
        show_on_dashboard=v.show_on_dashboard, note=v.note,
        stream_name=v.stream_name or "",
        play_url=_play_url(v.name) if v.enabled else None,
        go2rtc_url=_go2rtc_url(v.stream_name) if v.enabled else None,
    )


@router.get("", response_model=list[VideoOut])
def list_videos(
    robot_id: int | None = Query(None, description="只看这台设备的相机"),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator", "viewer")),
) -> list[VideoOut]:
    stmt = select(VideoSource).order_by(VideoSource.id)
    if robot_id is not None:
        stmt = stmt.where(VideoSource.robot_id == robot_id)
    rows = db.scalars(stmt).all()
    return [_out(v) for v in rows]


@router.get("/go2rtc-streams")
def list_go2rtc_streams(
    all: bool = Query(False, description="true 时列出 go2rtc 全部流（排障用）"),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator", "viewer")),
) -> dict:
    """把 go2rtc 里已有的流列出来，前端直接选，不用手打流名。

    `_web` 结尾的是给浏览器用的（H265 已转 H264），优先选这些。
    """
    import json as _json
    import urllib.request as _req

    base = getattr(get_settings(), "go2rtc_base", "") or ""
    if not base:
        return {"ok": False, "reason": "未配置 JC_GO2RTC_BASE", "streams": []}
    try:
        with _req.urlopen(f"{base.rstrip('/')}/api/streams", timeout=5) as r:
            data = _json.loads(r.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 - 中继不可达只影响这个下拉
        return {"ok": False, "reason": f"go2rtc 不可达：{exc.__class__.__name__}", "streams": []}

    registered = {v.stream_name for v in db.query(VideoSource).all() if v.stream_name}

    out = []
    for name, info in data.items():
        producers = info.get("producers") or []
        source = ""
        if producers:
            source = producers[0].get("url") or producers[0].get("source") or ""
        out.append({
            "name": name,
            "source": mask_url(source) if source else "",
            "web": name.endswith("_web"),
            "ready": bool(producers),
            "registered": name in registered,
        })
    out.sort(key=lambda x: (not x["web"], x["name"]))
    if not all:
        # 默认只给已登记的：现场不需要看到 lab1–lab6 这些测试流
        out = [x for x in out if x["registered"]]
    return {"ok": True, "streams": out}


@router.post("", response_model=VideoOut, dependencies=[Depends(require_csrf)])
def create_video(
    body: VideoIn,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin")),
) -> VideoOut:
    if body.vendor not in VENDORS:
        raise BadRequest("厂商只能是 hikvision/dahua/other", code="BAD_VENDOR")
    split_url(body.url)  # 提前校验
    v = VideoSource(**body.model_dump())
    db.add(v)
    db.commit()
    db.refresh(v)
    audit(db=db, action="video.create", target=v.name, user=me,
          detail={"vendor": v.vendor, "group": v.group_name})
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


_LIVE_CACHE: dict[int, tuple[bytes, float]] = {}


@router.get("/{video_id}/live.jpg")
def live_jpg(
    video_id: int,
    _: User = Depends(require_roles("admin", "operator", "viewer")),
):
    """代理 go2rtc 的一帧。

    为什么不让前端 iframe 播：go2rtc 播放器会铺满容器（裁掉两边）并在断流时把
    "mse: dial tcp ..." 糊在画面上。首页要的是"看全、干净"，用图片 + contain 最稳；
    需要流畅播放就点「打开全屏页」。
    """
    import urllib.request as _req

    from fastapi import Response

    from app.core.errors import ExternalUnavailable

    # 查库要快拿快放：抓帧可能阻塞 3.5 秒，占着会话会把连接池抽干
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        v = db.get(VideoSource, video_id)
        stream_name = v.stream_name if v else ""
    if not stream_name:
        raise NotFound("视频源不存在或未设置流名")
    base = getattr(get_settings(), "go2rtc_base", "") or ""
    if not base:
        raise ExternalUnavailable("未配置 go2rtc", code="NO_GO2RTC")
    # 与实时预览一致：优先用 _web 转码变体抓帧
    frame_src = f"{stream_name}_web" if _has_web_variant(stream_name, base) else stream_name
    url = f"{base.rstrip('/')}/api/frame.jpeg?src={frame_src}"
    import time as _time

    try:
        with _req.urlopen(url, timeout=3.5) as resp:
            data = resp.read()
        if len(data) < 1024:
            raise RuntimeError("空帧")
        _LIVE_CACHE[video_id] = (data, _time.time())
    except Exception as exc:  # noqa: BLE001
        cached = _LIVE_CACHE.get(video_id)
        # 30 秒内有过画面：先返回旧帧（标 X-Frame-Stale），前端不闪断
        if cached and _time.time() - cached[1] < 30:
            return Response(content=cached[0], media_type="image/jpeg",
                            headers={"Cache-Control": "no-store", "X-Frame-Stale": "1"})
        raise ExternalUnavailable(f"抓帧失败：{exc.__class__.__name__}", code="FRAME_FAIL") from exc
    return Response(content=data, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


@router.get("/health")
def videos_health(
    robot_id: int | None = Query(None),
    ids: str | None = Query(None, description="只探这几路，逗号分隔（首页只探显示的两路）"),
    _: User = Depends(require_roles("admin", "operator", "viewer")),
) -> dict:
    """每路流实际能不能出画面（不是"配置了没有"，是真抓一帧）。"""
    from app.services.snapshot import probe_frame

    from app.db.session import SessionLocal

    base = getattr(get_settings(), "go2rtc_base", "") or ""
    with SessionLocal() as db:
        q = db.query(VideoSource).filter(VideoSource.show_on_dashboard.is_(True))
        if robot_id is not None:
            q = q.filter(VideoSource.robot_id == robot_id)
        if ids:
            want = [int(x) for x in ids.split(",") if x.strip().isdigit()]
            if want:
                q = q.filter(VideoSource.id.in_(want))
        rows = [(v.id, v.name, v.stream_name or "") for v in q.all()]

    # 探测在会话外做（每路最多 2 次 × 2.5s，不能占连接）
    out = []
    for vid, name, stream in rows:
        ok, reason = probe_frame(stream, base)
        out.append({"id": vid, "name": name, "stream": stream, "ok": ok, "reason": reason})
    return {"ok": True, "videos": out}


@router.get("/{video_id}/mjpeg")
def mjpeg(
    video_id: int,
    _: User = Depends(require_roles("admin", "operator", "viewer")),
):
    """低延迟预览：共享一条上游转码流，浏览器 <img> 直接显示。

    每路摄像头只有一个 ffmpeg（和 detask 里 go2rtc 承担的角色一样），
    观众只是从「最新一帧」缓存里取，首帧只付一次握手成本。
    """
    from app.core.errors import ExternalUnavailable
    from app.services.video_stream import FPS, FFMPEG, registry

    if not FFMPEG:
        raise ExternalUnavailable("服务端没有 ffmpeg，无法转码", code="FFMPEG_MISSING")
    # 查库不占流式会话：长连接期间不能一直攥着连接
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        v = db.get(VideoSource, video_id)
        src = v.url if v else None
        stream_name = (v.stream_name or "") if v else ""
    if not src:
        raise NotFound("视频源不存在")
    # 面板显示哪路流，转码就用哪路流的源（否则会出现"选的培训室、看到的走廊"）
    from app.core.config import get_settings as _gs

    _base = getattr(_gs(), "go2rtc_base", "") or ""
    src = _rtsp_for_stream(stream_name, _base) or src

    stream = registry.acquire(video_id, _upstream(src))
    boundary = "frame"

    def gen():
        try:
            # 等第一帧（最多 8 秒），拿不到就当作源不可用
            deadline = time.time() + 8
            while stream.frame() is None:
                if time.time() > deadline or not stream.running:
                    return
                time.sleep(0.05)

            while True:
                frame = stream.frame()
                if frame is None:
                    if not stream.running:
                        return
                    time.sleep(0.05)
                    continue
                stream.last_used = time.time()
                yield (f"--{boundary}\r\n"
                       f"Content-Type: image/jpeg\r\n"
                       f"Content-Length: {len(frame)}\r\n\r\n").encode() + frame + b"\r\n"
                time.sleep(1.0 / FPS)
        finally:
            registry.release(video_id)

    return StreamingResponse(gen(), media_type=f"multipart/x-mixed-replace; boundary={boundary}")


@router.get("/streams/stats")
def stream_stats(_: User = Depends(require_roles("admin", "operator"))):
    """看当前有几路在转码、各自几个观众 —— 排查 CPU 和连接数用。"""
    from app.services.video_stream import registry

    return registry.stats()


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
        _log_snapshot_fail(v.name)
        raise ExternalUnavailable("抓帧失败，检查地址/账号/网络", code="SNAPSHOT_FAILED")

    _SNAP_CACHE[video_id] = (time.time(), proc.stdout)
    return Response(content=proc.stdout, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


_snap_fail_ts: dict[str, float] = {}


def _log_snapshot_fail(name: str) -> None:
    """抓帧失败留痕，但同一路 60 秒只记一条，避免每 2 秒刷一条。"""
    import time as _t
    from app.services.messages import audit, store as msg_store

    now = _t.time()
    if now - _snap_fail_ts.get(name, 0) < 60:
        return
    _snap_fail_ts[name] = now
    msg_store.add("warn", "video", f"抓帧失败：{name}", "检查摄像头地址/账号/网络",
                  {"to": "cameras"})


def _g2_base() -> str:
    base = getattr(get_settings(), "go2rtc_base", "") or ""
    if not base:
        raise BadRequest("未配置 JC_GO2RTC_BASE，无法注册到 go2rtc", code="NO_GO2RTC")
    return base.rstrip("/")


def _g2_call(method: str, path: str) -> int:
    import urllib.request as _req

    req = _req.Request(_g2_base() + path, method=method)
    try:
        with _req.urlopen(req, timeout=8) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        raise BadRequest(f"go2rtc 返回 {exc.code}", code="GO2RTC_ERROR") from exc
    except OSError as exc:
        raise BadRequest(f"go2rtc 不可达：{exc.__class__.__name__}", code="GO2RTC_UNREACHABLE") from exc


def _slug(name: str, video_id: int) -> str:
    import re as _re

    s = _re.sub(r"[^a-zA-Z0-9_]+", "_", name).strip("_").lower()
    return f"jc_{s}" if s else f"jc_{video_id}"


@router.post("/{video_id}/register-go2rtc", dependencies=[Depends(require_csrf)])
def register_go2rtc(
    video_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> dict:
    """把这一路视频源注册进 go2rtc：原始流 + `_web`（浏览器可放的 H264）。

    调的是 go2rtc 的 PUT /api/streams，热生效，不用重启、不用改 yaml。
    """
    from urllib.parse import quote

    v = db.get(VideoSource, video_id)
    if not v:
        raise NotFound("视频源不存在")

    name = _slug(v.name, v.id)
    web_name = f"{name}_web"
    from app.services.messages import audit, store as msg_store

    try:
        _g2_call("PUT", f"/api/streams?name={name}&src={quote(v.url, safe='')}")
        _g2_call("PUT", f"/api/streams?name={web_name}&src={quote(f'ffmpeg:{name}#video=h264', safe='')}")
    except Exception as exc:  # noqa: BLE001 - 失败要留痕，再往上抛
        msg_store.add("danger", "video", f"go2rtc 注册失败：{v.name}",
                      f"{exc.__class__.__name__}：检查 go2rtc 是否可达", {"to": "cameras"})
        raise

    # 确认 go2rtc 真的认了这两个流
    import json as _json
    import urllib.request as _req

    with _req.urlopen(_g2_base() + "/api/streams", timeout=8) as r:
        streams = _json.loads(r.read().decode("utf-8", "replace"))
    if web_name not in streams:
        raise BadRequest("go2rtc 未确认新流", code="GO2RTC_NOT_CONFIRMED")

    v.stream_name = web_name
    db.commit()
    db.refresh(v)

    from app.services.messages import audit, store as msg_store
    audit(db=db, action="video.register", target=v.name, user=_, detail={"stream": web_name})
    msg_store.add("info", "video", f"视频源已注册：{v.name}",
                  f"go2rtc 流 {web_name}（厂商 {VENDORS.get(v.vendor, v.vendor)}）",
                  {"to": "video", "query": {"source": str(v.id)}})
    return {"ok": True, "stream": name, "web_stream": web_name, "video": _out(v)}


@router.delete("/{video_id}", dependencies=[Depends(require_csrf)])
def delete_video(
    video_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin")),
) -> dict:
    v = db.get(VideoSource, video_id)
    if not v:
        raise NotFound("视频源不存在")
    db.delete(v)
    db.commit()
    audit(db=db, action="video.delete", target=v.name, user=me)
    return {"ok": True}
