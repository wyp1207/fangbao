"""真机基础运动测试：站定 -> 起步(踏步) -> 前进 1.5s -> 停 -> 读状态。

安全：用户确认场地清空、急停在手。任何异常立即发零速度。
约定：轴指令 0x21010130(前后) / 0x21010131(左右) / 0x21010135(转向)，
值域 ±1000，|值|<=655 视为 0（文档公式），所以用 700 表示"缓慢前进"。
"""

from __future__ import annotations

import sys
import time

sys.path.insert(0, r"D:\Desktop\防爆机器人\server")

from app.adapters.deeprobotics.protocol import (  # noqa: E402
    CMD_START_STOP, X30Client, send_motion,
)

AXIS_FWD = 0x21010130
AXIS_LEFT = 0x21010131
AXIS_YAW = 0x21010135

c = X30Client("192.168.1.106", 30000, timeout=4.0)


def state(tag: str) -> dict:
    st = c.status()
    print(f"{tag}: MotionState={st.get('MotionState')} Pos=({st.get('PosX')},{st.get('PosY')}) "
          f"Yaw={st.get('AngleYaw')} Location={st.get('Location')} Speed={st.get('Speed')}")
    return st


def axis(code: int, value: int) -> None:
    send_motion(code, value=value)


def all_stop() -> None:
    for code in (AXIS_FWD, AXIS_LEFT, AXIS_YAW):
        try:
            axis(code, 0)
        except Exception:  # noqa: BLE001
            pass


try:
    st = state("起立后")
    if str(st.get("MotionState")) not in ("2", "3", "4"):
        print("不在站立/踏步状态，先退出（请先起立）")
        raise SystemExit(1)

    print("发送『开始运动』(0x21010201) …")
    print("  UDP:", send_motion(CMD_START_STOP))
    time.sleep(2)
    st = state("起步后")
    if str(st.get("MotionState")) != "4":
        print("⚠️ MotionState 不是 4（踏步），仍尝试轴指令（部分固件 2/3 也能走）")

    print("前进：0x21010130 = 700，持续 1.5s（每 100ms 重发）…")
    t0 = time.time()
    while time.time() - t0 < 1.5:
        axis(AXIS_FWD, 700)
        time.sleep(0.1)
    print("发零速度 …")
    all_stop()
    time.sleep(1.5)
    st = state("停止后")

    print("发送『停止运动』(0x21010201) …")
    print("  UDP:", send_motion(CMD_START_STOP))
    time.sleep(1)
    state("收尾")
finally:
    all_stop()
    c.close()
