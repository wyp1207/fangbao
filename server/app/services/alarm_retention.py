"""告警 / AI 证据保留期清理。

为什么单独做：AI 证据图是整张 JPEG，单条几百 KB；一天几千条时磁盘先满，
然后 MySQL 写失败，整个平台跟着挂。默认保留 30 天，可在设置里改。

规则：
- 超过保留期的 `ai_result` 删除，并删除对应图片文件（只允许删 AI_SHOT_ROOT 下的）；
- 超过保留期的 `alarm_record` 删除，但**已转工单的告警保留**，避免工单断链；
- 工单、审计不删。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai import AiResult
from app.models.alarm import AlarmRecord
from app.models.inspection import WorkOrder
from app.services.snapshot import AI_SHOT_ROOT

log = logging.getLogger(__name__)


def _unlink_image(image_path: str | None, root: Path) -> bool:
    if not image_path:
        return False
    try:
        p = Path(image_path)
        if not p.is_absolute():
            p = root / p
        p = p.resolve()
        root = root.resolve()
        if root not in p.parents:
            log.warning("拒绝删除证据图：路径不在 AI_SHOT_ROOT 下 %s", p)
            return False
        if p.is_file():
            p.unlink()
            return True
    except OSError:
        log.warning("删除证据图失败 %s", image_path, exc_info=True)
    return False


def purge_old_alarms(db: Session, keep_days: int = 30,
                     image_root: Path | None = None) -> dict:
    """删除超过保留期的 AI 结果/图片和未转工单的告警。调用方负责 commit。"""
    days = max(1, int(keep_days))
    cutoff = datetime.now() - timedelta(days=days)
    root = image_root or AI_SHOT_ROOT

    ai_rows = db.query(AiResult).filter(AiResult.ts < cutoff).all()
    images = 0
    for row in ai_rows:
        if _unlink_image(row.image_path, root):
            images += 1
    for row in ai_rows:
        db.delete(row)
    db.flush()

    linked = select(WorkOrder.source_id).where(
        WorkOrder.source == "alarm", WorkOrder.source_id.is_not(None)
    )
    old_alarms = (
        db.query(AlarmRecord)
        .filter(AlarmRecord.started_at < cutoff, ~AlarmRecord.id.in_(linked))
        .all()
    )
    for a in old_alarms:
        db.delete(a)
    db.flush()

    return {
        "keep_days": days,
        "ai_results": len(ai_rows),
        "images": images,
        "alarms": len(old_alarms),
    }
