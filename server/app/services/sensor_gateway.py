"""环境数据采集网关：Modbus TCP / MQTT → 平台读数。

为什么做在服务端而不是让现场自己写脚本：
- 现场气体报警器大多只支持 Modbus RTU/TCP 或 MQTT，没有 HTTP；
- 让客户 IT 写采集脚本 = 把不确定性丢给甲方，出问题还是找我们。

形态：平台里起一个采集线程，按配置轮询/订阅，读到的值走和手工录入**同一条**
入库+判阈值路径（`services/sensor_io.py`），所以告警、报表、恢复逻辑天然一致。

Modbus 客户端没有引第三方库：MBAP 头 + 功能码 03/04 就够，约 50 行。
MQTT 用 paho-mqtt（业界标准库），没装时该类型网关直接报"未安装"，不静默失败。
"""

from __future__ import annotations

import json
import logging
import socket
import struct
import threading
import time
from datetime import datetime

log = logging.getLogger(__name__)


# ---------------- Modbus TCP（最小实现） ----------------

def _mbap(transaction_id: int, unit_id: int, pdu: bytes) -> bytes:
    return struct.pack(">HHHB", transaction_id, 0, len(pdu) + 1, unit_id) + pdu


def modbus_read(host: str, port: int, unit_id: int, start: int, count: int,
                *, timeout: float = 3.0, function: int = 3) -> list[int]:
    """读保持寄存器（03）或输入寄存器（04）。返回 16 位无符号列表。"""
    tid = int(time.time() * 1000) & 0xFFFF
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(_mbap(tid, unit_id,
                           struct.pack(">BHH", function, start, count)))
        header = sock.recv(7)
        if len(header) < 7:
            raise ConnectionError("Modbus 响应过短")
        _tid, _proto, length, _unit = struct.unpack(">HHHB", header)
        body = b""
        while len(body) < length - 1:
            chunk = sock.recv(length - 1 - len(body))
            if not chunk:
                break
            body += chunk
    if not body:
        raise ConnectionError("Modbus 空响应")
    if body[0] & 0x80:
        raise ConnectionError(f"Modbus 异常码 {body[1]}")
    byte_count = body[1]
    data = body[2:2 + byte_count]
    if len(data) < count * 2:
        raise ConnectionError(f"Modbus 数据不足：期望 {count*2} 字节，拿到 {len(data)}")
    return list(struct.unpack(f">{count}H", data[:count * 2]))


def scale(raw: int, spec: dict) -> float:
    """寄存器原始值 → 工程值。scale=0.1 表示原值要乘 0.1。"""
    return round(raw * float(spec.get("scale", 1)) + float(spec.get("offset", 0)), 4)


# ---------------- 采集线程 ----------------

class SensorGatewayRunner:
    """按库里的网关配置采集。每个网关一个线程，失败退避重连。"""

    def __init__(self, session_factory) -> None:
        self._sf = session_factory
        self._stop = threading.Event()
        self._threads: dict[int, threading.Thread] = {}
        self._status: dict[int, dict] = {}
        self._mqtt_clients: dict[int, object] = {}

    # ---- 生命周期 ----
    def start_all(self) -> None:
        from app.models.sensor_gateway import SensorGateway

        with self._sf() as db:
            rows = db.query(SensorGateway).filter(SensorGateway.enabled.is_(True)).all()
            ids = [(g.id, g.name, g.protocol) for g in rows]
        for gid, name, proto in ids:
            self.start(gid, name, proto)

    def start(self, gid: int, name: str, proto: str) -> None:
        if gid in self._threads and self._threads[gid].is_alive():
            return
        t = threading.Thread(target=self._loop, args=(gid, name, proto), daemon=True,
                             name=f"gw-{gid}")
        self._threads[gid] = t
        t.start()

    def stop_all(self) -> None:
        self._stop.set()
        for c in self._mqtt_clients.values():
            try:
                c.loop_stop()  # type: ignore[attr-defined]
                c.disconnect()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass

    def status(self) -> list[dict]:
        return [{"id": k, **v} for k, v in self._status.items()]

    def _loop(self, gid: int, name: str, proto: str) -> None:
        backoff = 5
        while not self._stop.is_set():
            try:
                if proto == "modbus":
                    self._poll_modbus(gid)
                elif proto == "mqtt":
                    self._run_mqtt(gid)
                    return        # MQTT 是订阅模型，自己维持连接
                else:
                    log.warning("网关 %s 协议 %s 暂不支持", name, proto)
                    return
                self._status[gid] = {"state": "ok", "ts": datetime.now().isoformat(timespec="seconds")}
                backoff = 5
            except Exception as exc:  # noqa: BLE001
                self._status[gid] = {"state": "error", "error": f"{exc.__class__.__name__}: {exc}",
                                     "ts": datetime.now().isoformat(timespec="seconds")}
                log.warning("网关 %s 采集失败：%s", name, exc)
            if self._stop.wait(self._interval(gid) if proto == "modbus" else backoff):
                break

    def _interval(self, gid: int) -> int:
        from app.models.sensor_gateway import SensorGateway

        with self._sf() as db:
            g = db.get(SensorGateway, gid)
            return max(int(g.interval_s) if g and g.interval_s else 10, 3)

    # ---- Modbus ----
    def _poll_modbus(self, gid: int) -> None:
        from app.models.sensor_gateway import SensorGateway
        from app.services.sensor_io import ingest_value

        with self._sf() as db:
            g = db.get(SensorGateway, gid)
            if g is None or not g.mapping_json:
                return
            mapping = json.loads(g.mapping_json)
            host, port, unit = g.host, int(g.port), int(g.unit_id or 1)

        for item in mapping:
            regs = modbus_read(host, port, unit, int(item["register"]), 1,
                               function=int(item.get("function", 3)))
            value = scale(regs[0], item)
            with self._sf() as db:
                ingest_value(db, sensor_id=int(item["sensor_id"]), value=value,
                             source="gateway")

    # ---- MQTT ----
    def _run_mqtt(self, gid: int) -> None:
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:  # pragma: no cover - 依赖缺失时明确报错
            raise RuntimeError("未安装 paho-mqtt，无法使用 MQTT 网关") from exc

        from app.models.sensor_gateway import SensorGateway
        from app.services.sensor_io import ingest_value
        from app.db.session import SessionLocal

        with self._sf() as db:
            g = db.get(SensorGateway, gid)
            host, port, topic = g.host, int(g.port), g.topic or "#"
            mapping = json.loads(g.mapping_json or "{}")
            user, pwd = g.username, g.password

        def on_message(_client, _userdata, msg):  # noqa: ANN001
            try:
                payload = json.loads(msg.payload.decode() or "{}")
            except Exception:  # noqa: BLE001
                return
            # 约定：payload = {"sensor_id": 3, "value": 12.5} 或 {"温度": 25.1}（按 mapping 名称映射）
            sensor_id = payload.get("sensor_id") or mapping.get(msg.topic) or mapping.get(payload.get("key"))
            value = payload.get("value", payload.get("val"))
            if sensor_id is None or value is None:
                return
            with SessionLocal() as db:
                ingest_value(db, sensor_id=int(sensor_id), value=float(value), source="gateway")

        c = mqtt.Client(client_id=f"jcrob-gw-{gid}", protocol=mqtt.MQTTv311)  # type: ignore[attr-defined]
        if user:
            c.username_pw_set(user, pwd or "")
        c.on_message = on_message
        c.connect(host, port, keepalive=30)
        c.subscribe(topic, qos=0)
        self._mqtt_clients[gid] = c
        self._status[gid] = {"state": "subscribed", "topic": topic,
                             "ts": datetime.now().isoformat(timespec="seconds")}
        c.loop_forever(retry_first_connection=True)


runner: SensorGatewayRunner | None = None
