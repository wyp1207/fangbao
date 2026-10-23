"""SLA：告警优先级 → 响应时限，以及工单超时判定。

对标依据：报警响应时限由「后果 × 允许响应时间」决定（ISA-18.2），
工单时限按缺陷等级（紧急立即 / 重大一周 / 一般半年，南网口径）落到 due_at。
这里只做一层映射，时限可在「系统设置」改，不写死在业务代码里。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

DEFAULT_MINUTES = {"P1": 30, "P2": 120, "P3": 480, "P4": 1440}


def matrix() -> dict[str, int]:
    """读设置里的 SLA 矩阵；坏数据回落到默认，不让报错拖垮建单。"""
    try:
        from app.api.v1.settings import load_all

        raw = load_all().get("alarm.sla_minutes")
        if isinstance(raw, dict) and raw:
            return {k: int(v) for k, v in raw.items() if str(v).isdigit()}
        if isinstance(raw, str):
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return {k: int(v) for k, v in parsed.items() if str(v).isdigit()}
    except Exception:  # noqa: BLE001
        pass
    return dict(DEFAULT_MINUTES)


def minutes_for(priority: str | None, level: str | None = None) -> int:
    m = matrix()
    if priority and priority in m:
        return m[priority]
    # 没有分级的老数据按严重度回落
    if level == "critical":
        return m.get("P2", 120)
    if level == "warn":
        return m.get("P3", 480)
    return m.get("P4", 1440)


def due_at(priority: str | None, level: str | None = None,
           now: datetime | None = None) -> datetime:
    return (now or datetime.now()) + timedelta(minutes=minutes_for(priority, level))


def label(priority: str) -> str:
    m = matrix()
    mins = m.get(priority, DEFAULT_MINUTES.get(priority, 0))
    if mins < 60:
        return f"{mins} 分钟"
    if mins < 1440:
        return f"{mins // 60} 小时"
    return f"{mins // 1440} 天"
