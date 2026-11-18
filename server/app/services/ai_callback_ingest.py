"""真实回调（.170 盒子 webhook）→ `ai_result` + 证据图落盘。

为什么单独一个 service、不塞进 api 层：
回调入口的职责只是"原样收下、落盘、回 200"；把"这 18 个字段怎么变成平台
字段"放在这里，才能单测字段映射，也不会因为入库/下载失败把回调打回 5xx
（盒子收到非 2xx 会一直重推）。

真实 payload（2026-11-18 15:55:34）的关键结构：
`result_data` 是**列表**（一个回调可带多个任务的执行结果），框在
`result_data[].result_data.task_result.object_list[]`，不是顶层的 `object_list`。

两条纪律：
1. 测试包必须丢：盒子联调时会推 `2006-01-02` 的假时间和 `example.com` 的假图，
   进了库就会把"今日告警数"和图片目录一起污染。
2. 图片只是证据：下载失败/超限/不是 JPEG 都只记 `result_json.image_error`，
   `ai_result` 照写、`image_path` 留空——不能因为图挂了把识别结果也丢了。

入库之后调 `ai_alarm.evaluate` 决定要不要建告警。告警判断失败只记日志：
盒子收到非 2xx 会一直重推，不能因为告警这条支路把已经入库的结果再打回去。
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ai import AiResult
from app.services import ai_alarm

log = logging.getLogger(__name__)

# 回调来源固定为 1：真实回调只有 .170 这一路，幂等键 = (1, snowflake_id)
CALLBACK_SOURCE_ID = 1
IMAGE_ROOT = Path(__file__).resolve().parents[2] / "data" / "ai_images"
IMAGE_BASE_ENV = "AI170_IMAGE_BASE"
# 盒子上报的图片地址是它自己的内网地址（172.16.8.2:8081），平台只能走 NAT
DEFAULT_IMAGE_BASE = "http://192.168.1.170:8081"
DOWNLOAD_TIMEOUT_S = 5.0
MAX_IMAGE_MB = 3
MAX_IMAGE_BYTES = MAX_IMAGE_MB * 1024 * 1024
JPEG_MAGIC = b"\xff\xd8"
# 盒子联调/压测用的假日期与假域名；命中任一即视为测试包
TEST_TS_PREFIX = "2006-01-02"
TEST_URL_MARKER = "example.com"
ALGORITHM_MAX_LEN = 48
CAMERA_NAME_MAX_LEN = 64
SOURCE_URL_MAX_LEN = 512
EVENT_ID_MAX_LEN = 64
TS_FMT = "%Y-%m-%d %H:%M:%S"


class ImageDownloadError(RuntimeError):
    """图片下载/校验失败；只影响 image_path，不影响入库。"""


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_text(value: Any, limit: int) -> str:
    text = str(value if value is not None else "").strip()
    return text[:limit]


def _image_base() -> str:
    return (os.environ.get(IMAGE_BASE_ENV) or "").strip().rstrip("/") or DEFAULT_IMAGE_BASE


def _rewrite_url(url: str, base: str) -> str:
    """只换 scheme/host/port，path+query 原样保留。

    盒子的 `alarm_pic_url` 指向 172.16.8.2（它自己的网卡），平台侧不可达；
    改写成 `AI170_IMAGE_BASE`（默认 http://192.168.1.170:8081）才能下载。
    """
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        target = urlsplit(base)
    except ValueError:
        return url[:SOURCE_URL_MAX_LEN]
    if not parts.scheme or not parts.netloc:
        return url[:SOURCE_URL_MAX_LEN]
    return urlunsplit((target.scheme or parts.scheme, target.netloc or parts.netloc,
                       parts.path, parts.query, ""))[:SOURCE_URL_MAX_LEN]


def _object_list(body: dict[str, Any]) -> list[dict[str, Any]]:
    """`result_data[].result_data.task_result.object_list[]` → 扁平框列表。"""
    tasks = body.get("result_data")
    if isinstance(tasks, dict):
        tasks = [tasks]
    if not isinstance(tasks, list):
        return []

    boxes: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        inner = task.get("result_data")
        if not isinstance(inner, dict):
            continue
        result = inner.get("task_result")
        if not isinstance(result, dict):
            continue
        items = result.get("object_list")
        if isinstance(items, list):
            boxes.extend(item for item in items if isinstance(item, dict))
    return boxes


def normalize_callback(body: Any) -> dict[str, Any] | None:
    """真实回调 body → 平台字段；测试包/非回调 body 返回 None（丢弃）。"""
    if not isinstance(body, dict):
        return None

    event_id = _as_text(body.get("snowflake_id"), EVENT_ID_MAX_LEN)
    ts_text = _as_text(body.get("timestamp"), 32)
    pic_url = _as_text(body.get("alarm_pic_url"), 1024)
    # 没有雪花 id / 时间戳的 body 不是这路回调（旧的自定义 payload 也在内）
    if not event_id or not ts_text:
        return None
    if ts_text.startswith(TEST_TS_PREFIX) or TEST_URL_MARKER in pic_url.lower():
        log.info("AI 回调是测试包（ts=%s url=%s），丢弃", ts_text, pic_url[:120])
        return None
    try:
        ts = datetime.strptime(ts_text, TS_FMT)
    except ValueError:
        log.info("AI 回调 timestamp 无法解析（%s），丢弃", ts_text[:32])
        return None

    boxes = _object_list(body)
    confidence = max((float(item.get("score") or 0.0) for item in boxes), default=0.0)
    return {
        "external_event_id": event_id,
        "algorithm": _as_text(body.get("algorithm_name"), ALGORITHM_MAX_LEN) or "unknown",
        "external_camera_id": _as_int(body.get("camera_id")),
        "external_camera_name": _as_text(body.get("camera_name"), CAMERA_NAME_MAX_LEN),
        "external_algorithm_id": _as_int(body.get("algorithm_id")),
        "confidence": confidence,
        "boxes": boxes,
        "ts": ts,
        "source_url": _rewrite_url(pic_url, _image_base()),
        "image_width": _as_int(body.get("image_width")),
        "image_height": _as_int(body.get("image_height")),
        "degree": _as_int(body.get("degree")),
        "analysis_job_id": _as_text(body.get("analysis_job_id"), 64),
        "raw": body,
    }


def download_image(url: str, *, timeout: float = DOWNLOAD_TIMEOUT_S,
                   max_bytes: int = MAX_IMAGE_BYTES) -> bytes:
    """取一张图，最多花 `timeout` 秒，读满 `max_bytes` 就中止。

    为什么自己算总时限：`urlopen(timeout=)` 只管单次 socket 操作，盒子半死不活
    地一滴一滴回数据时能拖很久；这里在每次读之间比对 wall clock，配合 socket
    超时把最坏情况压到 `2*timeout` 以内。
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ImageDownloadError(f"不支持的图片地址协议：{parts.scheme or '无'}")
    deadline = time.monotonic() + timeout
    req = urllib.request.Request(url, headers={"User-Agent": "jcrob-ai-callback/1.0"})
    chunks: list[bytes] = []
    total = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            while True:
                if time.monotonic() > deadline:
                    raise ImageDownloadError(f"图片下载超过 {timeout}s")
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ImageDownloadError(f"图片超过 {MAX_IMAGE_MB}MB 上限")
                chunks.append(chunk)
    except ImageDownloadError:
        raise
    except Exception as exc:  # noqa: BLE001 - 超时/DNS/HTTP 错误都只影响证据图
        raise ImageDownloadError(f"{type(exc).__name__}: {exc}") from exc
    return b"".join(chunks)


def _store_image(data: bytes, day: str) -> str:
    """校验后原子落盘，返回相对 `data/` 的路径（与 /api/v1/ai/results/{id}/image 一致）。"""
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageDownloadError(f"图片超过 {MAX_IMAGE_MB}MB 上限")
    if not data.startswith(JPEG_MAGIC):
        # 盒子 404 时回一页 HTML；存成 .jpg 会让"证据图"变成假证据
        raise ImageDownloadError("返回内容不是 JPEG")

    folder = IMAGE_ROOT / "callback" / day
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.jpg"
    path = folder / name
    tmp = folder / f".{name}.tmp"
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return f"ai_images/callback/{day}/{name}"


def _safe_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:255]


def _skip(reason: str) -> dict[str, Any]:
    return {"ingested": False, "skipped": True, "duplicate": False, "result_id": None,
            "image_path": None, "image_ok": False, "image_error": None, "reason": reason}


def _duplicate(result_id: int | None) -> dict[str, Any]:
    return {"ingested": False, "skipped": False, "duplicate": True, "result_id": result_id,
            "image_path": None, "image_ok": False, "image_error": None,
            "reason": "duplicate"}


def _find(db: Session, event_id: str) -> int | None:
    row = (
        db.query(AiResult.id)
        .filter(AiResult.source_id == CALLBACK_SOURCE_ID,
                AiResult.external_event_id == event_id)
        .first()
    )
    return row[0] if row else None


def ingest(db: Session, body: Any) -> dict[str, Any]:
    """归一化 + 幂等 + 下载图片 + 写一条 `ai_result`，再按规则决定是否建告警。

    返回 dict 而不是抛异常，调用方（回调接口）据此回 `ingested` 并保持 200。
    """
    item = normalize_callback(body)
    if item is None:
        return _skip("not_a_callback_payload")

    event_id = item["external_event_id"]
    existing = _find(db, event_id)
    if existing is not None:
        # 盒子重推/并发回调很常见：不重复下载图片，也不新增行
        log.info("AI 回调重复事件 event=%s result=%s，跳过", event_id, existing)
        return _duplicate(existing)

    image_path: str | None = None
    image_error: str | None = None
    if item["source_url"]:
        try:
            data = download_image(item["source_url"])
            image_path = _store_image(data, item["ts"].strftime("%Y%m%d"))
        except Exception as exc:  # noqa: BLE001 - 图挂了也要留识别结果
            image_error = _safe_error(exc)
            log.warning("AI 回调图片下载失败 event=%s: %s", event_id, image_error)

    rec = AiResult(
        source_id=CALLBACK_SOURCE_ID,
        external_event_id=event_id,
        # camera_id 是平台自己的相机台账 id；盒子 camera_id=13 还没映射，先留空
        algorithm=item["algorithm"],
        external_camera_id=item["external_camera_id"],
        external_camera_name=item["external_camera_name"],
        external_algorithm_id=item["external_algorithm_id"],
        source_url=item["source_url"],
        confidence=item["confidence"],
        ts=item["ts"],
        image_path=image_path,
        boxes_json=(json.dumps(item["boxes"], ensure_ascii=False)
                    if item["boxes"] else None),
        result_json=json.dumps({
            "kind": "callback",
            "raw": item["raw"],
            "source_url": item["source_url"],
            "analysis_job_id": item["analysis_job_id"],
            "image_width": item["image_width"],
            "image_height": item["image_height"],
            "degree": item["degree"],
            "image_error": image_error,
        }, ensure_ascii=False),
    )
    db.add(rec)
    try:
        db.commit()
    except IntegrityError:
        # 两个回调同时到：唯一键兜底，按重复处理，顺手把刚落盘的多余图删掉
        db.rollback()
        if image_path:
            (IMAGE_ROOT / "callback" / item["ts"].strftime("%Y%m%d")
             / Path(image_path).name).unlink(missing_ok=True)
        duplicate_id = _find(db, event_id)
        log.info("AI 回调并发重复 event=%s result=%s", event_id, duplicate_id)
        return _duplicate(duplicate_id)
    db.refresh(rec)

    log.info("AI 回调入库 result=%s event=%s camera=%s algorithm=%s boxes=%s image=%s",
             rec.id, event_id, item["external_camera_id"], item["algorithm"],
             len(item["boxes"]), image_path or f"失败({image_error})")

    # 告警是下游支路：规则没命中/去重/store 异常都不能影响"已入库"这个事实
    try:
        ai_alarm.evaluate(db, rec)
    except Exception as exc:  # noqa: BLE001 - 告警失败不阻塞入库
        log.warning("AI 告警评估失败 result=%s: %s: %s",
                    rec.id, type(exc).__name__, exc)

    return {"ingested": True, "skipped": False, "duplicate": False, "result_id": rec.id,
            "image_path": image_path, "image_ok": image_path is not None,
            "image_error": image_error, "reason": None}
