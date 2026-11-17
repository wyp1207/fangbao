"""CRIP 结果轮询：重叠窗 + 全分页 + 幂等写入。

为什么不是“只取第一页”：
盒子按 5s 轮询、事件突发时一页装不下；漏一页就永久丢事件。这里按 `total`
把所有页取完，重复 id 交给 `(source_id, external_event_id)` 唯一键和本层 `seen`
双保险。

为什么窗口要重叠 30s：
平台与盒子时钟即使对齐，也有边界抖动；`[cursor-30s, now]` 让边界事件至少被看两次，
幂等键保证不会写两条。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.adapters.ai.crip import CripClient, absolute_url
from app.models.ai import AiResult, AiSource

log = logging.getLogger(__name__)

OVERLAP = timedelta(seconds=30)
FIRST_LOOKBACK = timedelta(hours=24)
DEFAULT_PAGE_SIZE = 100
MAX_BACKOFF_S = 60.0
# 一次窗口最多翻多少页：盒子异常返回 total 却不减数据时，避免死循环
MAX_PAGES = 1000


class AiSyncError(RuntimeError):
    """同步配置/数据错误。"""


# ---------- 归一化 ----------


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_ts(value: Any) -> datetime:
    """盒子时间形如 `2026-11-17 12:34:56`；兼容 ISO/毫秒时间戳，解析失败退回当前时间。"""
    if isinstance(value, datetime):
        return value.replace(tzinfo=None, microsecond=0)
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e12 else value
        return datetime.fromtimestamp(seconds).replace(microsecond=0)
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(microsecond=0)
        except ValueError:
            continue
    return datetime.now().replace(microsecond=0)


def _extract_boxes(record: dict[str, Any]) -> list[dict[str, Any]]:
    """把盒子 `result` 归一化成 [{class_id,score,x,y,w,h}]；`result` 为空就是空列表。"""
    result = record.get("result")
    if not result:
        return []
    if isinstance(result, dict):
        items = (result.get("objects") or result.get("object_list")
                 or result.get("list") or [])
    elif isinstance(result, list):
        items = result
    else:
        return []

    boxes: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rect = item.get("rect") or item.get("bbox") or {}
        if not isinstance(rect, dict):
            continue
        boxes.append({
            "class_id": _as_int(item.get("class_id", item.get("classId"))),
            "score": float(item.get("score") or 0.0),
            "x": _as_int(rect.get("x")),
            "y": _as_int(rect.get("y")),
            "w": _as_int(rect.get("w", rect.get("width"))),
            "h": _as_int(rect.get("h", rect.get("height"))),
        })
    return boxes


def normalize_log(record: dict[str, Any], base_url: str) -> dict[str, Any]:
    """盒子 `LogRecordOld` → 平台字段。

    `raw_json` 原样保留整条记录；图片只拼 URL、不下载（Phase 4）。
    """
    raw = dict(record or {})
    event_id = raw.get("id")
    if event_id is None or str(event_id).strip() == "":
        raise AiSyncError("日志缺少 id，无法幂等写入")

    boxes = _extract_boxes(raw)
    confidence = max((b["score"] for b in boxes), default=0.0)
    return {
        "external_event_id": str(event_id),
        "camera_external_id": _as_int(raw.get("camera_id")),
        "camera_name": raw.get("camera_name") or "",
        "algorithm": raw.get("alert_type") or "",
        "degree": _as_int(raw.get("degree")),
        "ts": _parse_ts(raw.get("created_at")),
        "image_url": absolute_url(raw.get("url") or raw.get("origin"), base_url),
        "image_width": _as_int(raw.get("image_width")),
        "image_height": _as_int(raw.get("image_height")),
        "confidence": confidence,
        "boxes": boxes,
        "raw_json": raw,
    }


# ---------- 写入 ----------


def _write_result(db: Session, source_id: int, item: dict[str, Any]) -> bool:
    """同源同 external_event_id 已存在就跳过；返回是否新增。"""
    exists = (
        db.query(AiResult.id)
        .filter(AiResult.source_id == source_id,
                AiResult.external_event_id == item["external_event_id"])
        .first()
    )
    if exists:
        return False

    db.add(AiResult(
        source_id=source_id,
        external_event_id=item["external_event_id"],
        algorithm=(item["algorithm"] or "unknown")[:48],
        camera_id=item["camera_external_id"],
        confidence=item["confidence"],
        ts=item["ts"],
        # 图片先不下载；URL 和原始记录一起留档，后面要补图时不用再猜
        boxes_json=(json.dumps(item["boxes"], ensure_ascii=False)
                    if item["boxes"] else None),
        result_json=json.dumps(
            {"raw": item["raw_json"], "image_url": item["image_url"]},
            ensure_ascii=False,
        ),
    ))
    return True


def _pull_window(
    db: Session,
    source: AiSource,
    client: CripClient,
    start: datetime,
    end: datetime,
    page_size: int,
) -> dict[str, Any]:
    page = 1
    fetched = inserted = duplicates = pages = 0
    total = 0
    seen: set[str] = set()

    while page <= MAX_PAGES:
        result = client.search_logs(start, end, page=page, page_size=page_size)
        pages += 1
        total = max(total, result.total)
        if not result.records:
            break

        for raw in result.records:
            item = normalize_log(raw, source.base_url)
            event_id = item["external_event_id"]
            if event_id in seen:
                duplicates += 1
                continue
            seen.add(event_id)
            if _write_result(db, source.id, item):
                inserted += 1
            else:
                duplicates += 1
        fetched += len(result.records)

        if total and fetched >= total:
            break
        if len(result.records) < page_size:
            break
        page += 1

    db.flush()
    return {"total": total, "fetched": fetched, "inserted": inserted,
            "duplicates": duplicates, "pages": pages}


def _safe_error(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    return f"{type(exc).__name__}: {text}"[:255]


def _new_client(source: AiSource, client: CripClient | None) -> tuple[CripClient, bool]:
    if client is not None:
        return client, False
    prefix = (source.auth_ref or "AI170").strip() or "AI170"
    return CripClient.from_env(source.base_url, prefix=prefix), True


def _zero_stats() -> dict[str, Any]:
    return {"total": 0, "fetched": 0, "inserted": 0, "duplicates": 0, "pages": 0}


# ---------- 对外 ----------


def poll_once(
    db: Session,
    source_id: int,
    *,
    client: CripClient | None = None,
    now: datetime | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """拉一次增量窗口；失败不抛，写 `last_error` 并回滚本轮写入。

    返回 stats + ok/error，调用方据此决定退避（`backoff_delay`）。
    """
    source = db.get(AiSource, source_id)
    if source is None:
        raise AiSyncError(f"ai_source {source_id} 不存在")
    if not source.enabled:
        return {"ok": True, "skipped": True, "source_id": source_id,
                **_zero_stats(), "error": None}

    end = (now or datetime.now()).replace(microsecond=0)
    cursor = source.last_poll_at or (end - FIRST_LOOKBACK)
    start = (cursor - OVERLAP).replace(microsecond=0)
    crip, owns = _new_client(source, client)
    try:
        stats = _pull_window(db, source, crip, start, end, page_size)
        source.last_poll_at = end
        source.last_error = None
        db.commit()
        return {"ok": True, "source_id": source_id, "start": start, "end": end, **stats,
                "error": None}
    except Exception as exc:  # noqa: BLE001 - 轮询失败要让下一轮重拉，不能打断进程
        db.rollback()
        message = _safe_error(exc)
        log.warning("AI 轮询失败 source=%s: %s", source_id, message)
        fresh = db.get(AiSource, source_id)
        if fresh is not None:
            fresh.last_error = message
            db.commit()
        return {"ok": False, "source_id": source_id, "start": start, "end": end,
                **_zero_stats(), "error": message}
    finally:
        if owns:
            crip.close()


def backfill(
    db: Session,
    source_id: int,
    start: datetime,
    end: datetime,
    *,
    client: CripClient | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """补采指定时间范围；不动 `last_poll_at`，补采失败也不影响增量游标。"""
    source = db.get(AiSource, source_id)
    if source is None:
        raise AiSyncError(f"ai_source {source_id} 不存在")
    if end < start:
        raise AiSyncError("补采结束时间早于开始时间")

    crip, owns = _new_client(source, client)
    try:
        stats = _pull_window(db, source, crip, start, end, page_size)
        source.last_error = None
        db.commit()
        return {"ok": True, "source_id": source_id, "start": start, "end": end, **stats,
                "error": None}
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        message = _safe_error(exc)
        log.warning("AI 补采失败 source=%s: %s", source_id, message)
        fresh = db.get(AiSource, source_id)
        if fresh is not None:
            fresh.last_error = message
            db.commit()
        return {"ok": False, "source_id": source_id, "start": start, "end": end,
                **_zero_stats(), "error": message}
    finally:
        if owns:
            crip.close()


def backoff_delay(failures: int, base_interval: float, *, cap: float = MAX_BACKOFF_S) -> float:
    """连续失败退避：第 1 次保持基础间隔，之后翻倍，封顶 60s。"""
    base = float(base_interval)
    if failures <= 1:
        return min(base, cap)
    return min(base * (2 ** (failures - 1)), cap)


def poll_loop(
    session_factory: Callable[[], Session],
    source_id: int,
    *,
    stop: Callable[[], bool] | None = None,
    sleep: Callable[[float], None] | None = None,
    max_rounds: int | None = None,
) -> int:
    """可被后台线程调用的轮询循环；失败按 `backoff_delay` 退避。

    不默认启动：Phase 4 只交付能力，是否常驻由部署开关决定，避免本地开发
    无意中把盒子结果写进开发库。
    """
    import time

    sleeper = sleep or time.sleep
    failures = 0
    rounds = 0
    while stop is None or not stop():
        if max_rounds is not None and rounds >= max_rounds:
            break
        with session_factory() as db:
            result = poll_once(db, source_id)
            interval = 5.0
            source = db.get(AiSource, source_id)
            if source is not None and source.poll_interval_s:
                interval = float(source.poll_interval_s)
        rounds += 1
        if result["ok"]:
            failures = 0
            delay = interval
        else:
            failures += 1
            delay = backoff_delay(failures, interval)
        sleeper(delay)
    return rounds
