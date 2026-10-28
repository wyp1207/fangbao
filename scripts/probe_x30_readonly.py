"""只读探测 X30：1002 状态 / 2001 电量 / 1007 导航状态。不发任何运动指令。"""

import sys

sys.path.insert(0, r"D:\Desktop\防爆机器人\server")

from app.adapters.deeprobotics.protocol import X30Client  # noqa: E402

HOST = "192.168.1.106"
PORT = 30000

c = X30Client(HOST, PORT, timeout=4.0)
try:
    st = c.status()
    print("1002 status keys:", sorted(st.keys())[:20])
    for k in ("MotionState", "Electricity", "PosX", "PosY", "AngleYaw", "Location", "MapID",
              "NavStatus", "Speed", "Gait", "Posture", "ErrorCode"):
        if k in st:
            print(f"  {k} = {st.get(k)}")
    bt = c.battery()
    print("2001 battery:", {k: bt.get(k) for k in ("BatteryLevel", "Voltage", "Current") if k in bt})
    ns = c.nav_status()
    print("1007 nav:", {k: ns.get(k) for k in ("Status", "MapID", "PosX", "PosY") if k in ns})
finally:
    c.close()
