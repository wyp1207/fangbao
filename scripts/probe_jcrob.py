#!/usr/bin/env python3
"""JCROB read-only probe.

Only issues GET requests (plus optional WebSocket subscriptions). It never
calls motion, IO, task-start, PTZ-move or other write endpoints.

Usage:
  python probe_jcrob.py --base http://192.168.1.50:3546 --token <token>
  python probe_jcrob.py --base http://192.168.1.50:3546 \
      --username admin --password admin --ws --download-map

Outputs raw JSON/text under ./probe_out/<timestamp>/ and a summary.json.
The token is never written to disk or printed.

Sensitive fields (password / token / wifi / secret ...) are redacted before
anything is written to disk: the key is kept, the value becomes "***".
/system/config is additionally projected through CONFIG_VIEW_FIELDS, which is
the single whitelist shared with the platform Adapter ConfigView.

--angle-check resolves the unit of /system/galileo_status.currentAngle by
sampling it together with /navigation/pose.angle (degrees, per PDF p59) and
comparing circular errors under both hypotheses. It never guesses from a
single frame.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ENDPOINTS = [
    ("system_status", "/system/status", None),
    ("system_info", "/system/info", None),
    ("galileo_status", "/system/galileo_status", None),
    ("self_test", "/system/self_test", None),
    ("config", "/system/config", None),
    ("io", "/system/io", None),
    ("bw_io", "/system/bw_io", None),
    ("tts_playing", "/system/tts/playing", None),
    ("tts_records", "/system/tts/records", None),
    ("volume", "/system/volume", None),
    ("wifi", "/system/wifi", None),
    ("is_online", "/system/is_online", None),
    ("check_cert", "/system/check_cert", None),
    ("onvif_cameras", "/system/onvif_cameras", None),
    ("saved_images", "/system/saved_images", None),
    ("saved_videos", "/system/saved_videos", None),
    ("saved_maps", "/navigation/saved_maps", None),
    ("current_map", "/navigation/current_map", None),
    ("current_path", "/navigation/current_path", None),
    ("loop_task", "/navigation/loop_task", None),
    ("charge_pose", "/navigation/charge_pose", None),
    ("navigation_pose", "/navigation/pose", None),
    ("map_pose", "/map/pose", None),
    ("target_distance", "/navigation/target_distance", None),
    ("point_connections", "/navigation/point_connections", None),
    ("landmarks", "/navigation/landmarks", None),
    ("wind_info", "/navigation/wind_info", None),
    ("navigation_path", "/navigation/path", None),
    ("nav_points", "/navigation/nav_points", None),
    ("tasks", "/task", None),
    ("actions", "/action", None),
    ("blockly_tasks", "/blockly_task", None),
]


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

# 命中即脱敏，但保留 key 名：现场需要知道“字段存在过”，不需要它的值。
SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|pwd|secret|token|credential|ssid|wifi|private_key|api_?key)",
    re.IGNORECASE,
)

# /system/config 的白名单，字段名取自 PDF 第 19–20 页（5.0 前后两套命名都收）。
# wifi_ssid / wifi_password / lagrange_id / weixin_id 故意不在白名单内。
# 这是唯一一份定义：平台 server 端 ConfigView 必须与它一致，不要另写一套。
CONFIG_VIEW_FIELDS = frozenset({
    # 5.0 以后
    "default_map", "maps", "auto_charge", "slam_type",
    "lf_linear_v", "lf_theta_max", "lf_k2", "lf_kp", "lf_ki", "lf_kd",
    "lf_look_ahead_dist", "lf_xy_goal_tolerance", "lf_yaw_goal_tolerance",
    "lf_bar_distance_min", "lf_forward_max_dist", "lf_move_direction",
    "robot_radius", "astar_path_changeability", "go_charge_percentage",
    "use_smooth_switch_map",
    # 5.0 以前
    "navigation_speed", "max_control_speed", "bar_distance_min",
    "k2", "kp", "ki", "kd", "look_ahead_dist", "theta_max",
    "plan_width", "path_change", "forward_width", "rot_width", "backtime",
})


def redact(value):
    """递归脱敏：保留 key，敏感值替换为 "***"。"""
    if isinstance(value, dict):
        return {
            k: ("***" if SENSITIVE_KEY_RE.search(str(k)) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def project_config(data):
    """只保留白名单字段，其它一律丢弃（包括 wifi_password）。"""
    if not isinstance(data, dict):
        return data
    return {k: v for k, v in data.items() if k in CONFIG_VIEW_FIELDS}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="JCROB read-only HTTP/WS probe")
    p.add_argument("--base", required=True, help="e.g. http://192.168.1.50:3546")
    p.add_argument("--token", default="", help="robot token; never printed")
    p.add_argument("--username", default="", help="only used to fetch /token")
    p.add_argument("--password", default="", help="only used to fetch /token")
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--out", default="probe_out")
    p.add_argument("--ws", action="store_true", help="probe WS topics for 3 samples")
    p.add_argument("--ws-port", type=int, default=3547)
    p.add_argument("--download-map", action="store_true", help="download current map PNG")
    p.add_argument("--include-log", action="store_true", help="also GET /system/log")
    p.add_argument("--angle-check", action="store_true",
                   help="sample currentAngle vs pose.angle to resolve the angle unit")
    p.add_argument("--angle-check-seconds", type=float, default=30.0,
                   help="sampling window for --angle-check (default 30s, 1 Hz)")
    return p.parse_args()


def build_url(base: str, path: str, token: str, params: dict | None = None) -> str:
    q = dict(params or {})
    if token:
        q["token"] = token
    url = base.rstrip("/") + "/api/v1" + path
    if q:
        url += "?" + urllib.parse.urlencode(q)
    return url


def get(url: str, timeout: float) -> tuple[int, dict, bytes, float]:
    start = time.perf_counter()
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return r.status, dict(r.headers), body, (time.perf_counter() - start) * 1000
    except urllib.error.HTTPError as e:
        body = e.read()
        return e.code, dict(e.headers), body, (time.perf_counter() - start) * 1000


def decode_json(headers: dict, body: bytes):
    ctype = (headers.get("Content-Type") or headers.get("content-type") or "").lower()
    if "json" in ctype or body[:1] in (b"{", b"["):
        try:
            return json.loads(body.decode("utf-8"))
        except Exception:
            return None
    return None


def fetch_token(base: str, username: str, password: str, timeout: float) -> str:
    if not username:
        return ""
    url = build_url(base, "/token", "", {"username": username, "password": password})
    status, _, body, _ = get(url, timeout)
    if status != 200:
        print(f"[warn] /token returned HTTP {status}")
        return ""
    try:
        data = json.loads(body.decode("utf-8"))
        return data.get("token", "")
    except Exception:
        return ""


TEXT_SECRET_RE = re.compile(
    r"((?:token|password|passwd|pwd|secret|key)=)[^&\s\"']+", re.IGNORECASE
)


def scrub_text(body: bytes) -> tuple[bytes, bool]:
    """非 JSON 响应里的凭据也擦掉；二进制原样保留。"""
    try:
        text = body.decode("utf-8")
    except Exception:
        return body, False
    return TEXT_SECRET_RE.sub(r"\1***", text).encode("utf-8"), True


def probe_http(args, out_dir: Path, token: str) -> list[dict]:
    rows = []
    endpoints = list(ENDPOINTS)
    if args.include_log:
        endpoints.append(("system_log", "/system/log", None))

    for name, path, params in endpoints:
        url = build_url(args.base, path, token, params)
        shown = url.replace(token, "***") if token else url
        try:
            status, headers, body, ms = get(url, args.timeout)
        except Exception as e:
            rows.append({"name": name, "path": path, "status": "ERR", "error": str(e)})
            print(f"[ERR ] {name:20s} {path} {e}")
            continue

        data = decode_json(headers, body)
        if data is not None:
            safe = redact(data)
            if name == "config" and isinstance(safe, dict):
                # 配置只允许白名单字段带值；其余字段保留 key 名、值一律盖掉。
                # 这样现场仍能看到固件新增了哪些配置项，却不会把值带出机器人。
                safe = {
                    k: (v if k in CONFIG_VIEW_FIELDS else "***")
                    for k, v in safe.items()
                }
            (out_dir / f"{name}.json").write_text(
                json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if name == "config":
                (out_dir / "config_view.json").write_text(
                    json.dumps(project_config(safe), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            shape = list(safe.keys())[:12] if isinstance(safe, dict) else f"list[{len(safe)}]"
        else:
            scrubbed, scrubbed_ok = scrub_text(body)
            (out_dir / f"{name}.txt").write_bytes(scrubbed)
            shape = f"bytes[{len(body)}]" + ("" if scrubbed_ok else " binary")

        rows.append({
            "name": name, "path": path, "status": status, "ms": round(ms, 1),
            "bytes": len(body), "shape": shape, "url": shown,
        })
        print(f"[{status}] {name:20s} {path:45s} {ms:7.1f}ms {shape}")
    return rows


def probe_ws(args, out_dir: Path, token: str) -> list[dict]:
    try:
        import websocket  # type: ignore
    except Exception:
        print("[warn] websocket-client not installed; skip WS probe")
        return []

    host = urllib.parse.urlparse(args.base).hostname
    topics = [
        ("ws_galileo", "/galileo/status"),
        ("ws_env", "/bw_env_sensors/EnvSensorData"),
        ("ws_air", "/bw_env_sensors/AirSensorData"),
    ]
    rows = []
    for name, topic in topics:
        q = f"?token={urllib.parse.quote(token)}" if token else ""
        url = f"ws://{host}:{args.ws_port}{topic}{q}"
        samples = []
        try:
            ws = websocket.create_connection(url, timeout=args.timeout)
            for _ in range(3):
                ws.send("ping")
                samples.append(json.loads(ws.recv()))
                time.sleep(1)
            ws.close()
            (out_dir / f"{name}.json").write_text(
                json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            rows.append({"name": name, "topic": topic, "status": "OK", "samples": len(samples)})
            print(f"[OK  ] {name:20s} {topic} samples={len(samples)}")
        except Exception as e:
            rows.append({"name": name, "topic": topic, "status": "ERR", "error": str(e)})
            print(f"[ERR ] {name:20s} {topic} {e}")
    return rows


def _scalar(args, path: str, key: str, token: str):
    try:
        _, headers, body, _ = get(build_url(args.base, path, token), args.timeout)
        data = decode_json(headers, body)
        if isinstance(data, dict):
            return data.get(key)
    except Exception:
        pass
    return None


def wrap_pi(rad: float) -> float:
    return (rad + math.pi) % (2.0 * math.pi) - math.pi


def angle_check(args, out_dir: Path, token: str) -> dict:
    """多帧判定 currentAngle 的单位：度 还是 弧度。

    不靠单帧比值（角度接近 0 时两者都接近 0，比值无意义），
    也不直接比数值（yaw 过 ±180°/±π 会被环绕破坏）；
    对两种假设各算圆周误差，取误差更小且差距明显的那一个。
    """
    n = max(3, int(args.angle_check_seconds))
    samples = []
    for _ in range(n):
        ga = _scalar(args, "/system/galileo_status", "currentAngle", token)
        pa = _scalar(args, "/navigation/pose", "angle", token)
        samples.append({
            "t": datetime.now(timezone.utc).isoformat(),
            "currentAngle": ga,
            "pose_angle_deg": pa,
        })
        time.sleep(1.0)

    pairs = [
        (s["currentAngle"], s["pose_angle_deg"]) for s in samples
        if isinstance(s["currentAngle"], (int, float))
        and isinstance(s["pose_angle_deg"], (int, float))
        and not isinstance(s["currentAngle"], bool)
        and not isinstance(s["pose_angle_deg"], bool)
    ]
    result = {
        "samples": len(samples),
        "usable": len(pairs),
        "currentAngle_eq_minus1": sum(1 for ga, _ in pairs if ga == -1),
        "mean_abs_err_if_deg": None,
        "mean_abs_err_if_rad": None,
        "pose_spread_deg": None,
        "verdict": "inconclusive",
        "reason": "",
        "note": "-1 可能是未初始化的哨兵值；verdict=deg/rad 时 angle_unit_override 仍建议保留",
    }

    if len(pairs) < 3:
        result["reason"] = "可用样本不足（字段缺失或非数值）"
    else:
        err_deg = sum(
            abs(wrap_pi(math.radians(ga) - math.radians(pa))) for ga, pa in pairs
        ) / len(pairs)
        err_rad = sum(
            abs(wrap_pi(ga - math.radians(pa))) for ga, pa in pairs
        ) / len(pairs)
        ref = pairs[0][1]
        spread = max(abs(wrap_pi(math.radians(pa - ref))) for _, pa in pairs)
        result["mean_abs_err_if_deg"] = round(math.degrees(err_deg), 3)
        result["mean_abs_err_if_rad"] = round(math.degrees(err_rad), 3)
        result["pose_spread_deg"] = round(math.degrees(spread), 2)

        best = min(err_deg, err_rad)
        worst = max(err_deg, err_rad)
        if best > math.radians(15.0):
            result["reason"] = "两种假设误差都超过 15°，两接口可能不是同一时刻或未初始化"
        elif worst < best * 2.0:
            result["reason"] = "两种假设误差差距不足 2 倍，判不了；换一段机器人明显转向的采样"
        else:
            result["verdict"] = "deg" if err_deg < err_rad else "rad"
            result["reason"] = "圆周误差更小的一侧胜出"

    (out_dir / "angle_check.json").write_text(
        json.dumps({"result": result, "samples": samples}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[ANG ] currentAngle verdict={result['verdict']} "
          f"err_deg={result['mean_abs_err_if_deg']} err_rad={result['mean_abs_err_if_rad']} "
          f"spread={result['pose_spread_deg']}deg {result['reason']}")
    return result


def download_map(args, out_dir: Path, token: str) -> dict:
    try:
        _, _, body, _ = get(build_url(args.base, "/navigation/current_map", token), args.timeout)
        meta = json.loads(body.decode("utf-8"))
        name = meta.get("name", "")
        if not name:
            return {"status": "ERR", "error": "no current map name"}
        status, headers, png, _ = get(
            build_url(args.base, "/navigation/map_png", token, {"name": name}), args.timeout
        )
        if status == 200 and png:
            path = out_dir / f"map_{name}.png"
            path.write_bytes(png)
            return {"status": "OK", "map": name, "file": str(path), "bytes": len(png)}
        return {"status": status, "map": name}
    except Exception as e:
        return {"status": "ERR", "error": str(e)}


def main() -> int:
    args = parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out) / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    token = args.token or fetch_token(args.base, args.username, args.password, args.timeout)
    print(f"base={args.base} token={'set' if token else 'not-set'} out={out_dir}")

    rows = probe_http(args, out_dir, token)
    angle_result = angle_check(args, out_dir, token) if args.angle_check else {}
    ws_rows = probe_ws(args, out_dir, token) if args.ws else []
    map_result = download_map(args, out_dir, token) if args.download_map else {}

    summary = {
        "base": args.base,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "http": rows,
        "angle_check": angle_result,
        "ws": ws_rows,
        "map": map_result,
        "note": "read-only probe; no motion/write endpoints were called; "
                "sensitive fields redacted before writing",
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"summary: {out_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
