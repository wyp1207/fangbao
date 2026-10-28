"""设置项定义：默认值、类型、取值范围、影响谁。

这是"改了要真生效"的清单。新增设置项必须在这里登记，
否则前端拿不到说明、后端也不知道怎么校验。
"""

from __future__ import annotations

from typing import Any, Callable

# key -> 定义
# type: int | float | bool | str | choice
SCHEMA: dict[str, dict[str, Any]] = {
    # ---- 告警阈值 ----
    "alarm.sla_minutes": {
        "label": "SLA 响应时限（分钟，按 P1–P4）", "type": "json",
        "default": {"P1": 30, "P2": 120, "P3": 480, "P4": 1440},
        "group": "告警", "effect": "告警转工单时按优先级算 due_at；改完立即生效",
    },

    "alarm.battery_warn": {
        "label": "电量提醒阈值（%）", "type": "int", "default": 20, "min": 5, "max": 90,
        "group": "告警", "effect": "电量低于此值产生 warn 告警",
    },
    "alarm.battery_critical": {
        "label": "电量严重阈值（%）", "type": "int", "default": 10, "min": 1, "max": 60,
        "group": "告警", "effect": "电量低于此值产生 critical 告警",
    },
    "alarm.offline_after_s": {
        "label": "离线判定（秒）", "type": "int", "default": 10, "min": 3, "max": 300,
        "group": "告警", "effect": "超过这么久没收到机器人数据判定为通信中断",
    },
    "alarm.dedupe_s": {
        "label": "同类告警去重窗口（秒）", "type": "int", "default": 60, "min": 10, "max": 3600,
        "group": "告警", "effect": "同一指标在窗口内不重复产生告警",
    },
    "alarm.sustain_s": {
        "label": "告警持续确认（秒）", "type": "int", "default": 0, "min": 0, "max": 600,
        "group": "告警", "effect": "条件持续这么久才报，0=立即报（防抖）",
    },

    # ---- 告警外发 ----
    "notify.escalate_enabled": {
        "label": "严重告警超时升级", "type": "bool", "default": True,
        "group": "告警", "effect": "critical 未确认超时后转给值班长（tier=2 通道）",
    },
    "notify.escalate_after_min": {
        "label": "升级等待（分钟）", "type": "int", "default": 5, "min": 1, "max": 120,
        "group": "告警", "effect": "严重告警未确认超过这个时间就升级",
    },

    "robot.write_enabled": {
        "label": "允许下发任务（写操作）", "type": "bool", "default": False,
        "group": "平台",
        "effect": "关闭时下发/暂停/取消一律 403，并说明缺什么；真机联调通过并签授权后再开",
    },

    "map.strict_check": {
        "label": "地图严格校验", "type": "bool", "default": False,
        "group": "地图",
        "effect": "开启后：任务里的点位地图必须与当前激活地图一致，否则拒绝下发。"
                  "真机确认 map_id 字段后再开；现在是警告模式",
    },

    "security.idle_minutes": {
        "label": "空闲多久自动退出（分钟）", "type": "int", "default": 5, "min": 1, "max": 240,
        "group": "平台",
        "effect": "超过这么久没有鼠标/键盘操作，前端会核一次会话；已过期就退回登录页。值班大屏建议 10–30 分钟",
    },

    "sensor.keep_days": {
        "label": "环境读数保留（天）", "type": "int", "default": 90, "min": 1, "max": 3650,
        "group": "平台", "effect": "超过天数的传感器读数自动清理；告警记录不受影响",
    },

    "telemetry.keep_days": {
        "label": "运行数据保留（天）", "type": "int", "default": 7, "min": 1, "max": 3650,
        "group": "平台", "effect": "超过天数的遥测采样自动清理；报表口径以实际覆盖范围为准",
    },

    "clock.max_skew_s": {
        "label": "时钟偏差告警（秒）", "type": "int", "default": 2, "min": 1, "max": 600,
        "group": "平台", "effect": "机器人上报时间与平台差超过此值时告警（时间对不齐就没法复盘）",
    },

    # ---- 磁盘 ----
    "disk.warn_free_gb": {
        "label": "磁盘提醒（GB）", "type": "int", "default": 20, "min": 1, "max": 500,
        "group": "平台", "effect": "数据盘可用低于此值时提醒，不影响录像",
    },
    "disk.crit_free_gb": {
        "label": "磁盘严重（GB）", "type": "int", "default": 8, "min": 1, "max": 200,
        "group": "平台", "effect": "低于此值时告警；录像另有 5GB 硬停阈值",
    },

    # ---- 录像 ----
    "record.enabled": {
        "label": "启用录像", "type": "bool", "default": True,
        "group": "录像", "effect": "关掉后所有录制停止，已录文件保留",
    },
    "record.keep_days": {
        "label": "录像保留天数", "type": "int", "default": 30, "min": 1, "max": 365,
        "group": "录像", "effect": "超过天数的分段自动删除",
    },
    "record.max_gb": {
        "label": "录像容量上限（GB）", "type": "int", "default": 800, "min": 10, "max": 8000,
        "group": "录像", "effect": "超过后从最老的删到 70%",
    },
    "record.min_free_gb": {
        "label": "磁盘保护阈值（GB）", "type": "int", "default": 5, "min": 1, "max": 100,
        "group": "录像", "effect": "可用空间低于此值自动停录并告警",
    },

    # ---- 视频 ----
    "video.transcode_width": {
        "label": "转码宽度（px）", "type": "int", "default": 1280, "min": 480, "max": 3840,
        "group": "视频", "effect": "MJPEG 兜底流的缩放宽度，越小越省 CPU",
    },
    "video.mjpeg_fps": {
        "label": "首页视频帧率", "type": "int", "default": 20, "min": 1, "max": 25,
        "group": "视频", "effect": "go2rtc/HLS 都不可用时的 MJPEG 帧率",
    },

    # ---- 平台 ----
    "platform.name": {
        "label": "平台名称", "type": "str", "default": "智能巡检机器人管理平台",
        "group": "平台", "effect": "顶栏标题显示",
    },
    "platform.site": {
        "label": "默认场站", "type": "str", "default": "默认场站",
        "group": "平台", "effect": "新建地图/设备时的默认场站",
    },
    "platform.banner_on_fault": {
        "label": "能力异常时全站提示", "type": "bool", "default": True,
        "group": "平台", "effect": "go2rtc/机器人不可达时顶部显示黄条",
    },
}


def defaults() -> dict[str, Any]:
    return {k: v["default"] for k, v in SCHEMA.items()}


def cast(key: str, raw: Any) -> Any:
    """按 schema 把值转成正确类型并校验范围。"""
    spec = SCHEMA[key]
    t = spec["type"]
    if t == "json":
        import json as _json

        if isinstance(raw, (dict, list)):
            return raw
        try:
            return _json.loads(str(raw))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"{spec['label']} 需要合法 JSON") from exc
    if t == "bool":
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() in ("1", "true", "on", "yes")
    if t == "int":
        v = int(float(raw))
    elif t == "float":
        v = float(raw)
    else:
        return str(raw)[:200]
    if "min" in spec and v < spec["min"]:
        raise ValueError(f"{spec['label']} 不能小于 {spec['min']}")
    if "max" in spec and v > spec["max"]:
        raise ValueError(f"{spec['label']} 不能大于 {spec['max']}")
    return v


def describe() -> list[dict[str, Any]]:
    return [
        {"key": k, **{kk: vv for kk, vv in v.items() if kk != "default"}, "default": v["default"]}
        for k, v in SCHEMA.items()
    ]
