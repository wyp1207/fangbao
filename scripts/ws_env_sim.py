"""JCROB 环境 WS 模拟器（本地联调用）。

用法：
  python scripts/ws_env_sim.py --port 3550 --interval 5

按 SDK p107 的字段推 EnvSensorData；收到客户端 "ping" 就回 "pong"。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random

import websockets


def frame(seq: int, air: bool = False) -> str:
    if air:
        return json.dumps({
            "topic": "/bw_env_sensors/AirSensorData",
            "seq": seq,
            "data": {"co2": round(620 + random.uniform(-40, 60), 1),
                     "illuminance": round(320 + random.uniform(-30, 30), 1)},
        }, ensure_ascii=False)
    return json.dumps({
        "topic": "/bw_env_sensors/EnvSensorData",
        "seq": seq,
        "data": {
            "temperature": round(26.0 + random.uniform(-0.5, 0.5), 2),
            "rh": round(46.0 + random.uniform(-2, 2), 2),
            "smoke": round(0.02 + random.uniform(0, 0.02), 3),
            "pm2_5": round(18 + random.uniform(-4, 6), 1),
            "lel": round(3.0 + random.uniform(-0.6, 0.6), 2),
            "noise": round(52 + random.uniform(-3, 3), 1),
        },
    }, ensure_ascii=False)


async def handler(ws) -> None:
    path = getattr(getattr(ws, "request", None), "path", "") or ""
    air = "AirSensorData" in path
    print("client connected:", path or "?", flush=True)
    seq = 0

    async def sender() -> None:
        nonlocal seq
        while True:
            seq += 1
            await ws.send(frame(seq, air))
            await asyncio.sleep(interval)

    task = asyncio.create_task(sender())
    try:
        async for msg in ws:
            if isinstance(msg, str) and msg.strip().lower() == "ping":
                await ws.send("pong")
    except websockets.ConnectionClosed:
        pass
    finally:
        task.cancel()


async def main() -> None:
    global interval
    async with websockets.serve(handler, "0.0.0.0", args.port):
        print(f"env ws sim listening on ws://127.0.0.1:{args.port} (every {interval}s)", flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=3550)
    ap.add_argument("--interval", type=float, default=5.0)
    args = ap.parse_args()
    interval = args.interval
    asyncio.run(main())
