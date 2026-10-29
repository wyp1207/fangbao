"""云台控制（海康 ISAPI）。

说明：X30 本体 SDK 不管云台；现场的云台是海康双光谱相机（192.168.1.64），
走 ISAPI：PUT /ISAPI/PTZCtrl/channels/{ch}/continuous + /stop。
老项目 backend/hikvision.py 就是这么做的，这里补进平台。

安全：默认关闭（settings.ptz.enabled=false），配置好 IP/账号密码后打开；
每次 move 都是"发指令 → 停 150ms → 停"的脉冲，不会失控。
"""

from __future__ import annotations

import logging
import time

import httpx

from app.api.v1.settings import load_all

log = logging.getLogger(__name__)

CHANNEL = 1
SPEED = 8

_DIRS = {
    "up": (0, SPEED, 0),
    "down": (0, -SPEED, 0),
    "left": (-SPEED, 0, 0),
    "right": (SPEED, 0, 0),
    "zoom_in": (0, 0, 4),
    "zoom_out": (0, 0, -4),
}


def _cfg() -> dict:
    cfg = load_all()
    return {
        "enabled": bool(cfg.get("ptz.enabled")),
        "host": str(cfg.get("ptz.host") or "").strip(),
        "user": str(cfg.get("ptz.username") or "").strip(),
        "pwd": str(cfg.get("ptz.password") or ""),
        "channel": int(cfg.get("ptz.channel") or CHANNEL),
    }


def available() -> tuple[bool, str]:
    c = _cfg()
    if not c["enabled"]:
        return False, "云台未启用（系统设置 → 云台）"
    if not c["host"]:
        return False, "云台地址未配置"
    return True, ""


def _payload(pan: int, tilt: int, zoom: int) -> str:
    return (f"<PTZData><pan>{pan}</pan><tilt>{tilt}</tilt>"
            f"<zoom>{zoom}</zoom></PTZData>")


def _client(c: dict) -> httpx.Client:
    return httpx.Client(auth=httpx.DigestAuth(c["user"], c["pwd"]), timeout=5.0)


def move(direction: str, speed: int | None = None, pulse_ms: int = 150) -> tuple[bool, str]:
    okc, why = available()
    if not okc:
        return False, why
    if direction not in _DIRS:
        return False, f"不支持的方向：{direction}"
    c = _cfg()
    pan, tilt, zoom = _DIRS[direction]
    k = (speed or SPEED) / SPEED
    body = _payload(int(pan * k), int(tilt * k), int(zoom * k))
    url = f"http://{c['host']}/ISAPI/PTZCtrl/channels/{c['channel']}"
    try:
        with _client(c) as cli:
            r = cli.put(f"{url}/continuous", content=body.encode(),
                        headers={"Content-Type": "application/xml"})
            if r.status_code >= 300:
                return False, f"HTTP {r.status_code}: {r.text[:120]}"
            time.sleep(max(0.05, pulse_ms / 1000))
            # 注意：这台相机 /stop 返回 403，必须用 continuous 全 0 停
            cli.put(f"{url}/continuous", content=_payload(0, 0, 0).encode(),
                    headers={"Content-Type": "application/xml"})
        return True, ""
    except Exception as exc:  # noqa: BLE001
        log.warning("云台控制失败 direction=%s", direction, exc_info=True)
        return False, f"{exc.__class__.__name__}: {exc}"


def stop() -> tuple[bool, str]:
    okc, why = available()
    if not okc:
        return False, why
    c = _cfg()
    # 这台固件 /stop 是 403，continuous 全 0 才是官方认可的停
    url = f"http://{c['host']}/ISAPI/PTZCtrl/channels/{c['channel']}/continuous"
    try:
        with _client(c) as cli:
            r = cli.put(url, content=_payload(0, 0, 0).encode(),
                        headers={"Content-Type": "application/xml"})
        return r.status_code < 300, "" if r.status_code < 300 else f"HTTP {r.status_code}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{exc.__class__.__name__}: {exc}"


def position() -> dict:
    """读当前云台角度（elevation/azimuth），用于验证指令是否生效。"""
    okc, why = available()
    if not okc:
        return {"ok": False, "reason": why}
    c = _cfg()
    url = f"http://{c['host']}/ISAPI/PTZCtrl/channels/{c['channel']}/status"
    try:
        with _client(c) as cli:
            r = cli.get(url)
        if r.status_code != 200:
            return {"ok": False, "reason": f"HTTP {r.status_code}"}
        import re

        text = r.text
        out = {"ok": True}
        for key in ("elevation", "azimuth", "zoom"):
            m = re.search(rf"<{key}>(\d+)</{key}>", text)
            if m:
                out[key] = int(m.group(1))
        return out
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"{exc.__class__.__name__}: {exc}"}


def probe() -> tuple[bool, str]:
    """探测云台是否可连通（只读 ISAPI 设备信息，不动云台）。"""
    okc, why = available()
    if not okc:
        return False, why
    c = _cfg()
    url = f"http://{c['host']}/ISAPI/System/deviceInfo"
    try:
        with _client(c) as cli:
            r = cli.get(url)
        if r.status_code == 200:
            return True, r.text[:200]
        return False, f"HTTP {r.status_code}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{exc.__class__.__name__}: {exc}"
