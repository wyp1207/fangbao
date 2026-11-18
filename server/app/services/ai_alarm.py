"""AI 识别结果 → 平台告警（P1/P2 分级 + 置信度阈值 + 60s 去重）。

为什么单独一层、不写进 `ai_callback_ingest`：
入库只负责"把盒子的结果原样存下来"，告警是另一套口径——哪些相机、哪些算法、
多少置信度才算事，会随现场反馈反复调；分开才能单测这套规则，也才能做到
"告警判断失败不影响入库"（回调必须回 200，否则盒子会一直重推）。

规则（2026-11-18 现场确认）：
- 只对机器人自带相机建告警：12 dog、13 dog-云台、14 室外，可用
  `AI_ROBOT_CAMERA_IDS` 覆盖；固定相机的识别结果只入库、不打扰值班。
- P1（火焰/烟雾/行人闯入/消防通道堵塞）→ critical，置信度 ≥0.5；
- P2（安全帽/安全着装/工作服/反光衣/吸烟/摔倒/人员离岗）→ warn，置信度 ≥0.4；
- 其他算法（车辆违停/人员计数/玩手机/车牌…）→ 不告警；
- 同一 (external_camera_id, algorithm) 60s 内只建一条：一次闯入盒子会连续推
  好几帧，逐帧建告警等于刷屏。单 worker + 内存字典够用，重启丢窗口不是问题
  （重启后本来就该重新看现场，而不是继续压着不报）。
- 这里的相机维度窗口必须和 `AlarmStore.raise_external` 的 `dedupe_key` 一致：
  metric 是 `ai_{algorithm}`（告警中心按算法归类），但同算法在 12/13/14 三路
  相机上是三个独立现场事实，只按 metric 去重会把后两路静默吞掉。

`evaluate` 的 `now` / `store` 是刻意留的注入点：时间可注入才测得了 60/61 秒的
去重边界；store 可注入才能脱离数据库验证"建了什么级别的告警、消息长什么样"。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from sqlalchemy.orm import Session

from app.models.ai import AiResult
from app.services import alarms

log = logging.getLogger(__name__)

ROBOT_CAMERA_IDS_ENV = "AI_ROBOT_CAMERA_IDS"
DEFAULT_ROBOT_CAMERA_IDS = (12, 13, 14)
ROBOT_ID = 2                       # 机器人台账里 dog 的 id
DEDUPE_S = 60.0                    # 同相机同算法的静默窗口

# 顺序有意义：先按 P1 判，避免"安全帽"之类名字误落进 P1 的正则/子串
P1_ALGORITHMS = ("火焰", "烟雾", "行人闯入", "消防通道堵塞")
P2_ALGORITHMS = ("安全帽", "安全着装", "工作服", "反光衣", "吸烟", "摔倒", "人员离岗")
P1_MIN_CONFIDENCE = 0.5
P2_MIN_CONFIDENCE = 0.4

# (external_camera_id, algorithm) → 最近一次真正建告警的 monotonic 时刻
_last_raised: dict[tuple[int | None, str], float] = {}
_lock = threading.Lock()


def robot_camera_ids() -> set[int]:
    """机器人相机 id 集合；env 为空/无效时退回默认三路，而不是"全关"。"""
    raw = (os.environ.get(ROBOT_CAMERA_IDS_ENV) or "").strip()
    if not raw:
        return set(DEFAULT_ROBOT_CAMERA_IDS)
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            log.warning("%s 里有非数字项 %r，已忽略", ROBOT_CAMERA_IDS_ENV, part[:16])
    return ids or set(DEFAULT_ROBOT_CAMERA_IDS)


def level_for(algorithm: str) -> tuple[str, float] | None:
    """算法中文名 → (level, 最低置信度)；不在本轮的 P1/P2 清单里返回 None。"""
    name = algorithm or ""
    for keyword in P1_ALGORITHMS:
        if keyword in name:
            return "critical", P1_MIN_CONFIDENCE
    for keyword in P2_ALGORITHMS:
        if keyword in name:
            return "warn", P2_MIN_CONFIDENCE
    return None


def evaluate(db: Session, result: AiResult, *, now: float | None = None,
             store: Any = None) -> Any:
    """判断一条 `ai_result` 要不要建告警；建了就把 alarm 写回 `result.alarm_id`。

    返回 Alarm（或兼容对象）；不满足规则、被去重、store 不可用时返回 None。
    告警本身由 `AlarmStore` 落库，这里只负责规则，不重复实现持久化。
    任何 store/db 异常都向上抛，由调用方决定"告警失败不影响入库"。
    """
    algorithm = (result.algorithm or "").strip()
    rule = level_for(algorithm)
    if rule is None:
        return None
    level, min_confidence = rule

    camera_id = result.external_camera_id
    if camera_id not in robot_camera_ids():
        return None

    try:
        confidence = float(result.confidence or 0.0)
    except (TypeError, ValueError):
        return None
    if confidence < min_confidence:
        return None

    alarm_store = alarms.get_store() if store is None else store
    if alarm_store is None:
        log.warning("AlarmStore 未初始化，AI 告警跳过 algorithm=%s camera=%s",
                    algorithm, camera_id)
        return None

    ts = time.monotonic() if now is None else now
    key = (camera_id, algorithm)
    with _lock:
        last = _last_raised.get(key)
        if last is not None and ts - last < DEDUPE_S:
            return None
        # 先占位再调用：同一帧并发到两个请求时，也只允许一个真正建告警
        _last_raised[key] = ts

    camera_name = (result.external_camera_name or "").strip() or f"摄像头{camera_id}"
    message = f"{camera_name} 检测到 {algorithm}（置信度 {confidence:.2f}）"
    try:
        alarm = alarm_store.raise_external(
            metric=f"ai_{algorithm}",          # 告警中心口径：同一算法归到同一个 metric
            level=level,
            message=message,
            value=confidence,
            camera_id=None,
            robot_id=ROBOT_ID,
            # 但去重要按相机分开：同一算法在不同机器人相机上是不同的现场事实，
            # 只按 metric 去重会把第二台相机的告警吞掉。
            dedupe_key=f"{camera_id}:{algorithm}",
        )
    except Exception:
        # 没建成就不该占用去重窗口，否则一次故障会让这类告警静默 60s
        with _lock:
            _last_raised.pop(key, None)
        raise

    if alarm is None:
        # store 侧搁置/自身去重拒绝：同样不占窗口，解除搁置后还能再报
        with _lock:
            _last_raised.pop(key, None)
        log.info("AI 告警被 AlarmStore 拒绝（搁置或去重）algorithm=%s camera=%s",
                 algorithm, camera_id)
        return None

    result.alarm_id = alarm.id
    db.commit()
    log.info("AI 告警已建 result=%s alarm=%s camera=%s algorithm=%s level=%s conf=%.3f",
             result.id, alarm.id, camera_id, algorithm, level, confidence)
    return alarm
