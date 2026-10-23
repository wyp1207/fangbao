"""能力派生：外设 → 能力 → 面板。

规则只写在这一处：
- 外设 kind 决定能力（camera → video.live，thermal → video.thermal，gas → env.read.gas …）
- 本体动作（navigate/stand_up）来自适配器，不来自外设
- 不手填能力：capabilities_json 只作为"人工禁用"的覆盖项
"""

from __future__ import annotations

import json

KIND_CAPABILITIES: dict[str, list[str]] = {
    "camera": ["video.live", "photo.capture"],
    "thermal": ["video.thermal", "thermometry"],
    "ptz": ["ptz.move", "ptz.preset"],
    "gas": ["env.read.gas", "alarm.rule.gas"],
    "sf6": ["env.read.sf6", "alarm.rule.sf6"],
    "env": ["env.read"],
    "temp": ["env.read.temp"],
    "humidity": ["env.read.humidity"],
    "noise": ["env.read.noise"],
    "dust": ["env.read.dust"],
    "speaker": ["audio.tts"],
}

ADAPTER_ACTIONS: dict[str, list[str]] = {
    "deeprobotics_x30": ["navigate", "posture.stand_up", "posture.lie_down"],
    "jcrob_http": ["navigate"],
    "jcrob_mock": ["navigate"],
}


def derive(robot, peripherals: list) -> dict:
    """返回 {actions, capabilities, peripherals, panels}。"""
    caps: list[str] = []
    periph_out: list[dict] = []

    overrides = []
    if getattr(robot, "capabilities_json", None):
        try:
            data = json.loads(robot.capabilities_json)
            if isinstance(data, dict) and isinstance(data.get("disabled"), list):
                overrides = data["disabled"]
        except Exception:  # noqa: BLE001
            pass

    for p in peripherals:
        if not p.enabled:
            continue
        for c in KIND_CAPABILITIES.get(p.kind, []):
            if c not in caps and c not in overrides:
                caps.append(c)
        periph_out.append({
            "id": p.id, "kind": p.kind, "vendor": p.vendor,
            "channel": p.channel, "sensor_id": p.sensor_id, "video_id": p.video_id,
        })

    actions = [a for a in ADAPTER_ACTIONS.get(robot.adapter or "", []) if a not in overrides]

    # 面板顺序：视频（可见光→热红外）→ 环境 → 控制
    order = ["video.live", "video.thermal", "env.read.gas", "env.read.temp",
             "env.read.humidity", "env.read.noise", "env.read.dust", "ptz.move"]
    panels = [c for c in order if c in caps]
    panels += [c for c in caps if c not in order]

    return {
        "robot_id": robot.id,
        "adapter": robot.adapter,
        "actions": actions,
        "capabilities": caps,
        "peripherals": periph_out,
        "panels": panels,
    }
