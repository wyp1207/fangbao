"""没有硬件时造数据：Modbus TCP 模拟从站 + 可选 MQTT 发布。

用法：
    python tools_sensor_sim.py --port 15020            # 起 Modbus 模拟器
然后平台里建网关：host=127.0.0.1 port=15020 unit=1 register=1 scale=0.1
"""

from __future__ import annotations

import argparse
import math
import socket
import struct
import threading
import time


def serve_modbus(port: int, unit: int, values: list[int]) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))
    srv.listen(5)
    print(f"Modbus 模拟从站已启动 0.0.0.0:{port}（unit={unit}，寄存器 {len(values)} 个）")

    def handle(conn: socket.socket) -> None:
        with conn:
            while True:
                head = conn.recv(7)
                if len(head) < 7:
                    return
                tid, proto, length, uid = struct.unpack(">HHHB", head)
                pdu = conn.recv(length - 1)
                if len(pdu) < 5:
                    return
                func, start, count = struct.unpack(">BHH", pdu[:5])
                regs = values[start:start + count] or [0] * count
                payload = struct.pack(f">{count}H", *regs)
                body = struct.pack(">BB", func, count * 2) + payload
                conn.sendall(struct.pack(">HHHB", tid, 0, len(body) + 1, uid) + body)

    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=15020)
    ap.add_argument("--unit", type=int, default=1)
    ap.add_argument("--registers", type=int, default=8)
    args = ap.parse_args()

    values = [0] * args.registers
    threading.Thread(target=serve_modbus, args=(args.port, args.unit, values),
                     daemon=True).start()

    # 每 2 秒变一次：0 号寄存器模拟气体浓度（原值×0.1 = %LEL）
    t = 0
    try:
        while True:
            t += 1
            values[0] = int(abs(math.sin(t / 10)) * 80)      # 0~8.0 %LEL
            values[1] = 250 + int(50 * math.sin(t / 7))      # 温度 25.0±5 ℃
            values[2] = 500 + int(100 * math.sin(t / 11))    # 湿度 50±10 %
            time.sleep(2)
    except KeyboardInterrupt:
        print("已停止")


if __name__ == "__main__":
    main()
