"""写操作前置检查（纯函数，没有状态）。

签发写操作之前必须过这里。规则见 docs/平台方案-定稿.md §5.7。
等真机联调通过、采集表 01 表第 15–17 行签字后，再在下发入口调用；
在那之前，写接口整体不开放（robots.py 里 return 403）。
"""

from __future__ import annotations

from typing import Any


def precheck(*, status: dict[str, Any], info: dict[str, Any], inflight: bool = False,
             min_battery: int = 20) -> list[str]:
    """返回阻止下发的原因列表；空列表 = 可以下发。"""
    reasons: list[str] = []
    state = str(status.get("status", "")).lower()
    if state and state != "free":
        reasons.append(f"机器人当前状态是 {status.get('status')}，不是 Free")
    if info.get("driver_port"):
        reasons.append("硬件急停被按下")
    battery = info.get("battery")
    if isinstance(battery, (int, float)) and battery < min_battery:
        reasons.append(f"电量 {battery}% 低于阈值 {min_battery}%")
    if inflight:
        reasons.append("已有一个未完成的运动类命令")
    return reasons
