"""录像接口：开始/停止录制、分段列表、Range 回放、下载、删除。"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import require_csrf, require_roles
from app.core.errors import BadRequest, NotFound
from app.db.session import get_db
from app.models.user import User
from app.models.video_source import VideoSource
from app.services.recorder import (
    FFMPEG,
    probe_duration,
    registry,
    safe_path,
    segment_files,
)

router = APIRouter(prefix="/recordings", tags=["recordings"])


@router.get("")
def list_recordings(
    video_id: int | None = Query(default=None),
    limit: int = Query(default=200, le=1000),
    _: User = Depends(require_roles("admin", "operator", "viewer")),
) -> dict:
    files = segment_files(video_id)[:limit]
    return {"total": len(files), "items": files, "recording": registry.status()}


@router.get("/status")
def recording_status(
    _: User = Depends(require_roles("admin", "operator", "viewer")),
) -> dict:
    return {"recorders": registry.status(), "ffmpeg": bool(FFMPEG)}


@router.post("/{video_id}/start", dependencies=[Depends(require_csrf)])
def start_recording(
    video_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator")),
) -> dict:
    v = db.get(VideoSource, video_id)
    if not v:
        raise NotFound("视频源不存在")
    if not FFMPEG:
        raise BadRequest("服务端没有 ffmpeg，无法录像", code="FFMPEG_MISSING")
    rec = registry.start(video_id, v.name, v.url)
    return {"ok": True, "video_id": rec.video_id, "running": rec.running}


@router.post("/{video_id}/stop", dependencies=[Depends(require_csrf)])
def stop_recording(
    video_id: int,
    _: User = Depends(require_roles("admin", "operator")),
) -> dict:
    registry.stop(video_id)
    return {"ok": True, "video_id": video_id}


@router.get("/duration")
def duration(
    path: str,
    _: User = Depends(require_roles("admin", "operator", "viewer")),
) -> dict:
    p = safe_path(path)
    return {"path": path, "duration": probe_duration(p)}


@router.get("/file")
def stream_file(
    path: str,
    range_header: str | None = Header(default=None, alias="Range"),
    _: User = Depends(require_roles("admin", "operator", "viewer")),
):
    """支持 Range 的 mp4 输出，浏览器 `<video>` 才能拖动进度条。"""
    p = safe_path(path)
    size = p.stat().st_size
    if not range_header:
        return FileResponse(p, media_type="video/mp4", filename=os.path.basename(p))

    m = range_header.replace("bytes=", "").split("-")
    start = int(m[0]) if m[0] else 0
    end = int(m[1]) if len(m) > 1 and m[1] else size - 1
    if start >= size:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    end = min(end, size - 1)
    length = end - start + 1

    def gen():
        with p.open("rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(
        gen(), status_code=206, media_type="video/mp4",
        headers={
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
        },
    )


@router.delete("/file", dependencies=[Depends(require_csrf)])
def delete_file(
    path: str,
    _: User = Depends(require_roles("admin")),
) -> dict:
    p: Path = safe_path(path)
    p.unlink()
    return {"ok": True}


@router.delete("/{video_id}/all", dependencies=[Depends(require_csrf)])
def delete_all(
    video_id: int,
    _: User = Depends(require_roles("admin")),
) -> dict:
    files = [f for f in segment_files(video_id)]
    n = 0
    for f in files:
        try:
            safe_path(f["path"]).unlink()
            n += 1
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "deleted": n}


@router.get("/storage")
def storage(
    _: User = Depends(require_roles("admin", "operator", "viewer")),
) -> dict:
    from app.services.recorder import ROOT

    total = 0
    count = 0
    if ROOT.exists():
        for f in ROOT.rglob("*.mp4"):
            total += f.stat().st_size
            count += 1
    return {"files": count, "bytes": total, "dir": str(ROOT)}
