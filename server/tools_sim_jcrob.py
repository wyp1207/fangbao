"""JCROB 轮式机器人 HTTP 模拟器（本地测试用，不连真机）。

为什么需要：真机 11-10 才到，但 JCROB 适配器/轮询/写链路现在就要能测。
用 fixture 直接喂适配器测不到 HTTP 层（路径、编码、错误码），
这个模拟器把 3546 接口按真机路径跑起来，真机到了改个 IP 就切过去。

用法：
    python tools_sim_jcrob.py --port 3546            # 默认
    python tools_sim_jcrob.py --port 3546 --battery 42 --stuck   # 模拟低电量/卡住

接口路径与真机一致（见 adapters/jcrob/http_adapter.py 的 PATHS）：
    GET  /system/status /system/info /system/galileo_status
    GET  /navigation/pose /navigation/saved_maps /navigation/nav_points
    GET  /navigation/current_map /navigation/map_png /navigation/charge_pose
    GET  /task  /action
    POST /task（下发） /task/cancel（取消）
"""

from __future__ import annotations

import argparse
import json
import math
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
FIX = ROOT.parent / "contracts" / "jcrob" / "fixtures"

STATE = {
    "battery": 78.0,
    "started": time.time(),
    "task": None,
    "cancelled": 0,
}


def _fixture(name: str) -> dict | list:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def _pose() -> dict:
    t = time.time() - STATE["started"]
    return {"x": round(1.0 + 2 * math.cos(t / 25), 3),
            "y": round(-1.0 + 2 * math.sin(t / 25), 3),
            "angle": round((math.degrees(t / 25) + 90) % 360, 2)}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # 安静点
        pass

    def _json(self, payload, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, data: bytes, mime: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/api/v1"):
            path = path[len("/api/v1"):]
        if path == "/system/status":
            if STATE.get("stuck"):
                # 卡住：返回 RobotError 让平台判离线/自检失败
                return self._json({"status": "RobotError", "error": "SIM_STUCK"})
            return self._json(_fixture("system_status"))
        if path == "/system/info":
            d = dict(_fixture("system_info"))
            d["battery"] = int(round(STATE["battery"]))
            return self._json(d)
        if path == "/system/galileo_status":
            return self._json(_fixture("galileo_status"))
        if path == "/navigation/pose":
            return self._json(_pose())
        if path == "/navigation/saved_maps":
            return self._json(_fixture("saved_maps"))
        if path == "/navigation/current_map":
            return self._json(_fixture("current_map"))
        if path == "/navigation/nav_points":
            return self._json(_fixture("nav_points"))
        if path == "/navigation/charge_pose":
            return self._json(_fixture("charge_pose"))
        if path == "/navigation/map_png":
            qs = parse_qs(urlparse(self.path).query)
            name = (qs.get("name") or ["map1"])[0]
            try:
                return self._bytes(_map_png(), "image/png")
            except Exception:  # noqa: BLE001
                return self._json({"error": f"no map {name}"}, 404)
        if path == "/task":
            # 真机返回的是任务数组（见 contracts/jcrob/fixtures/task.json）
            return self._json([STATE["task"]] if STATE["task"] else [])
        if path == "/action":
            return self._json(_fixture("action"))
        return self._json({"error": "not found", "path": path}, 404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/api/v1"):
            path = path[len("/api/v1"):]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {}

        if path == "/task":
            STATE["task"] = {
                "id": body.get("id") or f"SIM-{int(time.time())}",
                "name": body.get("name") or "sim-task",
                "state": "RUNNING",
                "progress": 0,
                "path_data": body.get("path_data") or "",
            }
            return self._json({"ok": True, "id": STATE["task"]["id"]})
        if path == "/task/cancel":
            if STATE["task"]:
                STATE["task"]["state"] = "CANCELLED"
            STATE["cancelled"] += 1
            return self._json({"ok": True})
        return self._json({"error": "not found", "path": path}, 404)


def _map_png() -> bytes:
    """画一张 306×324 的灰度占位图（和 fixture 尺寸一致）。"""
    from PIL import Image, ImageDraw

    img = Image.new("L", (306, 324), 255)
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 280, 140], outline=0, width=3)
    d.rectangle([40, 160, 160, 300], outline=0, width=3)
    d.rectangle([180, 160, 280, 300], outline=0, width=3)
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=3546)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--battery", type=float, default=None, help="固定电量（默认 78 缓慢下降）")
    ap.add_argument("--stuck", action="store_true", help="模拟机器人异常（status=RobotError）")
    args = ap.parse_args()

    STATE["battery"] = args.battery if args.battery is not None else STATE["battery"]
    STATE["stuck"] = args.stuck

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"JCROB 模拟器已启动 http://{args.host}:{args.port}"
          f"{'（卡住模式）' if args.stuck else ''}")
    try:
        while True:
            if args.battery is None and not args.stuck:
                STATE["battery"] = max(5.0, STATE["battery"] - 0.02)
            if STATE["task"] and STATE["task"]["state"] == "RUNNING":
                STATE["task"]["progress"] = min(100, STATE["task"]["progress"] + 1)
                if STATE["task"]["progress"] >= 100:
                    STATE["task"]["state"] = "COMPLETE"
            time.sleep(3)
    except KeyboardInterrupt:
        print("已停止")


if __name__ == "__main__":
    raise SystemExit(main())
