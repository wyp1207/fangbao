"""JCROB 环境传感器 WebSocket 接入。

SDK 原文（PDF p106–107）：
  ws://<ip>:3547/<topic>?token=...     每秒必须发一次 ping
  /bw_env_sensors/EnvSensorData  → temperature / rh / smoke / pm1_0 / pm2_5 / pm10 / lel / noise
  /bw_env_sensors/AirSensorData  → co2 / illuminance

为什么单独一个服务而不是塞进适配器轮询：
轮询是"平台去问"，环境数据是"机器人主动推"，两套机制；混在一起会让
适配器的超时/合并逻辑变复杂（轮询失败不该影响环境流，反之亦然）。

收到数据后统一走 sensor_io.ingest_value——阈值判定、告警、滞回、去重全部复用，
不另写一套报警逻辑。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from app.db.session import SessionLocal

log = logging.getLogger(__name__)

ENV_TOPIC = "/bw_env_sensors/EnvSensorData"
AIR_TOPIC = "/bw_env_sensors/AirSensorData"

# SDK 字段 → 平台传感器类型（None 表示暂不接）
FIELD_KIND: dict[str, str] = {
    "temperature": "temperature",
    "rh": "humidity",
    "smoke": "smoke",
    "pm2_5": "pm",
    "pm25": "pm",
    "lel": "gas",
    "noise": "noise",
    "co2": "co2",
    "h2s": "h2s",
    "co": "co",
}

# 运行状态给 /robots/{id}/status 用，前端能看到"环境流有没有连上"
STATE: dict[int, dict[str, Any]] = {}


def parse_payload(raw: str | bytes) -> dict[str, float]:
    """把一帧 WS 文本解析成 {字段: 数值}。

    兼容三种常见形状：{"temperature":1}、{"data":{...}}、{"data":[{...}]}。
    解析不出数值的字段直接丢掉，不写 0 污染历史。
    """
    try:
        body = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {}

    def walk(node: Any, out: dict[str, float]) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool) and k in FIELD_KIND:
                    out[k] = float(v)
                else:
                    walk(v, out)
        elif isinstance(node, list):
            for item in node:
                walk(item, out)

    out: dict[str, float] = {}
    walk(body, out)
    return out


def ensure_sensor(db, robot_id: int, kind: str, robot_name: str) -> int | None:
    """按（设备, 类型）找传感器，没有就建，并登记成外设（首页面板据此出现）。"""
    from app.models.sensor import Sensor
    from app.models.video_source import VideoSource  # noqa: F401  保证模型已加载
    from app.api.v1.sensors import KINDS

    if kind not in KINDS:
        return None
    row = (db.query(Sensor)
           .filter(Sensor.robot_id == robot_id, Sensor.kind == kind)
           .first())
    if row is not None:
        return row.id

    label = KINDS[kind]["label"]
    row = Sensor(name=f"{robot_name} {label}", kind=kind, unit=KINDS[kind]["unit"],
                 station="", robot_id=robot_id, enabled=True)
    db.add(row)
    db.commit()
    db.refresh(row)

    try:
        from app.models.peripheral import Peripheral

        if not db.query(Peripheral).filter(Peripheral.sensor_id == row.id).first():
            db.add(Peripheral(robot_id=robot_id, kind=kind, vendor="jcrob",
                              model="bw_env_sensors", sensor_id=row.id, enabled=True))
            db.commit()
    except Exception:  # noqa: BLE001
        log.warning("传感器 #%s 建外设失败（不影响采集）", row.id)
    log.info("环境流自动建传感器 #%s %s（设备 %s）", row.id, label, robot_id)
    return row.id


async def _ingest(robot_id: int, robot_name: str, values: dict[str, float]) -> int:
    from app.services.sensor_io import ingest_value

    written = 0
    with SessionLocal() as db:
        for field, value in values.items():
            kind = FIELD_KIND.get(field)
            if not kind:
                continue
            sid = ensure_sensor(db, robot_id, kind, robot_name)
            if sid is None:
                continue
            try:
                ingest_value(db, sensor_id=sid, value=value, source="jcrob_ws")
                written += 1
            except Exception:  # noqa: BLE001
                log.exception("环境流写库失败 sensor=%s value=%s", sid, value)
    return written


async def _run_one(robot_id: int, name: str, host: str, port: int, token: str = "") -> None:
    import websockets

    st = STATE.setdefault(robot_id, {"connected": False, "last_msg_ts": 0.0,
                                     "fields": 0, "last_error": ""})
    backoff = 1.0
    while True:
        url_base = f"ws://{host}:{port}"
        q = f"?token={token}" if token else ""
        try:
            async with websockets.connect(f"{url_base}{ENV_TOPIC}{q}", open_timeout=5,
                                          ping_interval=None, max_size=2 ** 20) as ws:
                st.update(connected=True, last_error="", since=time.time())
                log.info("环境流已连接 %s %s", name, f"{host}:{port}")
                backoff = 1.0
                last_ping = 0.0
                while True:
                    # SDK 要求每秒一次文本 ping，否则服务端会断
                    now = time.time()
                    if now - last_ping >= 1.0:
                        await ws.send("ping")
                        last_ping = now
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    if raw in ("ping", "pong", b"ping", b"pong"):
                        continue
                    values = parse_payload(raw)
                    if not values:
                        continue
                    n = await _ingest(robot_id, name, values)
                    st.update(last_msg_ts=time.time(), fields=n)
        except asyncio.CancelledError:
            st.update(connected=False)
            raise
        except Exception as exc:  # noqa: BLE001
            st.update(connected=False, last_error=f"{exc.__class__.__name__}: {exc}")
            log.warning("环境流断开 %s（%s），%.0fs 后重连", name, exc.__class__.__name__, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


class EnvWsRunner:
    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task] = {}

    async def start(self, robots: list) -> None:
        await self.stop()
        for r in robots:
            if not getattr(r, "is_active", True):
                continue
            if (getattr(r, "adapter", "") or "") != "jcrob_http":
                continue
            # 开关：设备备注里带 no_env_ws 就不接（临时排障用，不改表）
            if "no_env_ws" in (getattr(r, "note", "") or ""):
                continue
            token = ""
            self._tasks[r.id] = asyncio.create_task(
                _run_one(r.id, r.name, r.ip, getattr(r, "ws_port", 3547) or 3547, token))
            log.info("环境流任务已登记：%s（ws://%s:%s）", r.name, r.ip, r.ws_port)
        if self._tasks:
            log.info("环境流共 %s 路", len(self._tasks))

    async def stop(self) -> None:
        for t in self._tasks.values():
            t.cancel()
        for t in self._tasks.values():
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks.clear()


runner = EnvWsRunner()


def state_for(robot_id: int) -> dict[str, Any]:
    st = STATE.get(robot_id)
    if not st:
        return {"supported": False}
    return {
        "supported": True,
        "connected": bool(st.get("connected")),
        "age_s": round(time.time() - st["last_msg_ts"], 1) if st.get("last_msg_ts") else None,
        "fields": st.get("fields", 0),
        "last_error": st.get("last_error", ""),
    }
