"""X30 连通性探针：只发查询（1002 状态 / 2001 电池 / 1007 任务），不下发任何控制。

用法：
    python tools_probe_x30.py --host 192.168.1.106 --port 30000

在机器人网段的机器上跑（比如导航主机自己，或同网段的笔记本）。
输出原始 XML，用来确认真实字段名——不要凭文档猜字段。
"""

from __future__ import annotations

import argparse
import socket

from app.adapters.deeprobotics.protocol import X30Client


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=30000)
    ap.add_argument("--timeout", type=float, default=5.0)
    args = ap.parse_args()

    print(f"目标 {args.host}:{args.port}（TCP 本体监控协议，只读）")

    # 先探端口，报错要说人话
    try:
        with socket.create_connection((args.host, args.port), timeout=args.timeout):
            print("  端口可达 ✓")
    except Exception as exc:  # noqa: BLE001
        print(f"  端口不通：{exc.__class__.__name__}: {exc}")
        print("  排查：是否同网段 / 是否配置了到 192.168.1.0/24 的路由 / 机器人是否上电")
        return 2

    c = X30Client(args.host, args.port, args.timeout)
    for label, fn in (("实时状态 1002", c.query_status),
                      ("电池信息 2001", c.query_battery),
                      ("任务状态 1007", c.query_task)):
        try:
            print(f"\n== {label} ==")
            print(fn())
        except Exception as exc:  # noqa: BLE001
            print(f"  失败：{exc.__class__.__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
