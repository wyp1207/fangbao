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
                elif proto == "modbus_rtu_ssh":
                    self._poll_rtu_ssh(gid)
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

    # ---- Modbus RTU over SSH（现场气表接在导航主机的串口上） ----
    RTU_SCRIPT = """
import serial, time
def crc16(d):
    c = 0xFFFF
    for b in d:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ (0xA001 if c & 1 else 0)
    return c
q = bytearray([{addr}, 0x03, {reg_hi}, {reg_lo}, 0x00, {count}])
c = crc16(q); q.append(c & 0xFF); q.append((c >> 8) & 0xFF)
# 串口刚释放时常丢第一帧：在进程内重试，比多开几次 SSH 稳
for attempt in range(3):
    try:
        s = serial.Serial("{dev}", {baud}, timeout=1)
        s.reset_input_buffer()
        s.write(q)
        time.sleep(0.35)
        r = s.read(64)
        s.close()
        if r and len(r) >= 5 and r[1] == 0x03:
            bc = r[2]
            d = r[3:3 + bc]
            print(",".join(str((d[j] << 8) | d[j + 1]) for j in range(0, len(d) - 1, 2)))
            break
        time.sleep(0.6)
    except Exception:
        time.sleep(0.6)
else:
    print("ERROR")
"""

    def _read_rtu_ssh(self, host: str, user: str, password: str, dev: str,
                      baud: int, addr: int, start: int, count: int) -> list[int]:
        """通过 SSH 在远程主机上跑一段串口读取脚本，返回寄存器值。

        为什么不用 Modbus TCP：现场气表是 RS485 转 USB 接在导航主机上，
        只有串口；导航主机不开放 Modbus 网关，只开 SSH。
        """
        import base64

        import paramiko

        script = self.RTU_SCRIPT.format(dev=dev, baud=baud, addr=addr,
                                        reg_hi=start >> 8, reg_lo=start & 0xFF,
                                        count=count)
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(host, username=user, password=password, timeout=6,
                        banner_timeout=6, auth_timeout=6)
            b64 = base64.b64encode(script.encode()).decode()
            # 串口被自带 gas_client 占着：先停它，读完再拉起来（旧系统也这么做）。
            # 注意必须分两次 exec：后台重启命令和读取混在一条里，stdout 会被吞掉。
            ssh.exec_command("pkill -9 -f gas_client 2>/dev/null; sleep 1.2", timeout=8)
            _, out, _err = ssh.exec_command(f"echo {b64} | base64 -d | python3", timeout=15)
            text = out.read().decode().strip()
            # 不再每次读完就把 gas_client 拉起来：它会立刻抢回串口，
            # 下一轮读又失败（实测成功率只有 4/5 且抖动）。
            # 平台运行期间独占串口；gas_client 由现场巡检脚本在停机后恢复。
            # ponytail: 这是"单写者"假设——同一串口不能两个进程同时读。
        finally:
            ssh.close()
        if not text or text == "ERROR" or text.startswith("ERROR"):
            # 刚释放串口时第一帧常丢，隔 0.8s 再读一次
            import time as _t

            _t.sleep(0.8)
            with paramiko.SSHClient() as ssh2:
                ssh2.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh2.connect(host, username=user, password=password, timeout=6,
                             banner_timeout=6, auth_timeout=6)
                b64b = base64.b64encode(script.encode()).decode()
                _, out2, _ = ssh2.exec_command(f"echo {b64b} | base64 -d | python3", timeout=15)
                text = out2.read().decode().strip()
        if not text or text.startswith("ERROR"):
            raise RuntimeError(f"串口读取失败（{dev}）：{text or '空响应'}")
        return [int(x) for x in text.split(",")]

    def _poll_rtu_ssh(self, gid: int) -> None:
        from app.models.sensor_gateway import SensorGateway
        from app.services.sensor_io import ingest_value

        with self._sf() as db:
            g = db.get(SensorGateway, gid)
            if g is None or not g.mapping_json:
                return
            mapping = json.loads(g.mapping_json)
            host, user, pw = g.host, g.username or "", g.password or ""
            dev = g.topic or "/dev/ttyUSB0"        # topic 字段复用为串口设备路径
            baud = int(g.port or 9600)             # port 字段复用为波特率
            addr = int(g.unit_id or 1)

        # 一次把需要的寄存器全读回来（同一串口，读两次更容易丢帧）
        regs_needed = [int(m.get("register", 0)) for m in mapping]
        start, count = min(regs_needed), max(regs_needed) - min(regs_needed) + 1
        values = self._read_rtu_ssh(host, user, pw, dev, baud, addr, start, count)
        for m in mapping:
            idx = int(m.get("register", 0)) - start
            if idx < 0 or idx >= len(values) or values[idx] == 65535:
                continue
            raw = values[idx]
            scale_k = float(m.get("scale", 1.0))
            with self._sf() as db:
                ingest_value(db, sensor_id=int(m["sensor_id"]), value=raw * scale_k,
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
