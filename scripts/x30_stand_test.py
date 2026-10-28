"""真机动作 1：起立（UDP 0x31010202 切换）。只做这一步，随后立刻读状态。

安全：场地已清空、急停在手（用户确认）。失败/超时自动停止，不再发任何指令。
"""

from __future__ import annotations

import sys
import time

sys.path.insert(0, r"D:\Desktop\防爆机器人\server")

from app.adapters.deeprobotics.protocol import (  # noqa: E402
    CMD_STAND_LIE, X30Client, send_motion,
)

c = X30Client("192.168.1.106", 30000, timeout=4.0)
try:
    before = c.status()
    print("起立前 MotionState=", before.get("MotionState"), "Location=", before.get("Location"),
          "电量=", before.get("Electricity"))
    if str(before.get("MotionState")) in ("2", "3"):
        print("已经是站立状态，不发指令")
        raise SystemExit(0)

    print("发送起立（UDP 192.168.1.103:43893, code=0x31010202）…")
    print("UDP 返回：", send_motion(CMD_STAND_LIE))

    deadline = time.time() + 30
    last = None
    while time.time() < deadline:
        time.sleep(2)
        st = c.status()
        ms = st.get("MotionState")
        if ms != last:
            print(f"  MotionState={ms} (0趴下/1起立中/2初始站立/3力控站立/5趴下中)")
            last = ms
        if str(ms) in ("2", "3"):
            print("✅ 已站立")
            print("  位姿:", st.get("PosX"), st.get("PosY"), "Location=", st.get("Location"))
            break
    else:
        print("⚠️ 30 秒内未到站立态，请现场确认")
finally:
    c.close()
