"""云深处 X30 本体监控协议（TCP 30000）编解码。

依据两处来源：
1. 官方文档《本体监控协议（TCP）》：头 16 字节、XML ASDU、Type 1002/1003/1004/1007/2001/2101；
2. 现场已在跑的桥接实现（8.40 上 robot-flask 的 dispatch.py）：实测头是 EB 90 EB 90，
   字段名为 MotionState / Electricity / PosX / PosY / Yaw / Speed / BatteryLevel / Voltage。

**两处对不上**：官方写 EB 91 EB 90，现场代码用 EB 90 EB 90 且能跑。
所以这里两种都认（读取时校验），发送默认用现场验证过的 EB 90 EB 90，
并提供 magic 参数；真机第一次连上后由探针确认到底哪个生效。
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from datetime import datetime
from xml.etree import ElementTree as ET

MAGIC_DOC = b"\xeb\x91\xeb\x90"    # 官方文档
MAGIC_FIELD = b"\xeb\x90\xeb\x90"  # 现场实现（默认）
MAGICS = (MAGIC_FIELD, MAGIC_DOC)
HEADER_LEN = 16

TYPE_STATUS = 1002
TYPE_NAV_TASK = 1003
TYPE_NAV_CANCEL = 1004
TYPE_NAV_QUERY = 1007
TYPE_BATTERY = 2001
TYPE_INIT_LOC = 2101

# 运动状态码（现场代码里的映射）
MOTION_STATES = {
    "0": "趴下", "1": "起立中", "2": "初始站立", "3": "力控站立",
    "4": "踏步", "5": "趴下中", "6": "软急停", "7": "摔倒",
}
NAV_STATES = {"0": "完成", "1": "执行中", "-1": "无法执行"}

MOTION_STAND = 18
MOTION_LIE = 15


def build_asdu(msg_type: int, items: dict | None = None, command: str = "1") -> bytes:
    inner = "".join(f"<{k}>{v}</{k}>" for k, v in (items or {}).items())
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><PatrolDevice>'
           f'<Type>{msg_type}</Type><Command>{command}</Command>'
           f'<Time>{ts}</Time><Items>{inner}</Items></PatrolDevice>')
    return xml.encode("utf-8")


def frame(asdu: bytes, msg_id: int, magic: bytes = MAGIC_FIELD) -> bytes:
    return magic + struct.pack("<HH", len(asdu), msg_id & 0xFFFF) + b"\x00" * 8 + asdu


def parse_asdu(xml_bytes: bytes) -> dict:
    """XML → 扁平 dict（Items 下的键提到顶层，重复键保留第一个）。"""
    out: dict[str, str] = {}
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out
    for child in root:
        if child.tag == "Items":
            for item in child:
                out.setdefault(item.tag, (item.text or "").strip())
        else:
            out.setdefault(child.tag, (child.text or "").strip())
    return out


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("连接被关闭")
        buf += chunk
    return buf


def read_frame(sock: socket.socket) -> tuple[bytes, bytes]:
    """返回 (magic, asdu)。"""
    head = _recv_exact(sock, HEADER_LEN)
    magic = head[:4]
    if magic not in MAGICS:
        raise ValueError(f"协议头未知: {magic.hex()}（文档 EB91EB90 / 现场 EB90EB90）")
    length, _mid = struct.unpack("<HH", head[4:8])
    if length <= 0 or length > 65535:
        raise ValueError(f"长度异常: {length}")
    return magic, _recv_exact(sock, length)


class X30Client:
    def __init__(self, host: str, port: int = 30000, timeout: float = 5.0,
                 magic: bytes = MAGIC_FIELD) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.magic = magic
        self._mid = 0
        self.last_magic: bytes | None = None
        # 复用连接：机器人每次新建连接要 0.1~8s（实测），频繁重连会一直超时
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()

    def _connect(self) -> socket.socket:
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        return sock

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def __del__(self) -> None:  # pragma: no cover
        self.close()

    def request(self, msg_type: int, items: dict | None = None,
                command: str = "1", timeout: float | None = None) -> dict:
        asdu = build_asdu(msg_type, items, command)
        t = timeout or self.timeout
        with self._lock:
            self._mid = (self._mid + 1) & 0xFFFF
            for attempt in (0, 1):
                try:
                    if self._sock is None:
                        self._sock = self._connect()
                    self._sock.settimeout(t)
                    self._sock.sendall(frame(asdu, self._mid, self.magic))
                    magic, body = read_frame(self._sock)
                    self.last_magic = magic
                    return parse_asdu(body)
                except (OSError, ValueError, ConnectionError):
                    self.close()
                    if attempt:
                        raise
        raise ConnectionError("unreachable")

    # ---- 只读 ----
    def status(self) -> dict:
        return self.request(TYPE_STATUS)

    def battery(self) -> dict:
        return self.request(TYPE_BATTERY)

    def nav_status(self) -> dict:
        return self.request(TYPE_NAV_QUERY)

    # ---- 控制（受写开关保护，由上层调用） ----
    def nav_goal(self, x: float, y: float, yaw: float = 0.0, map_id: int = 1,
                 speed: int = 1, gait: int = 0, timeout: float = 30) -> dict:
        return self.request(TYPE_NAV_TASK, {
            "Value": "1", "MapID": str(map_id), "PosX": str(x), "PosY": str(y),
            "PosZ": "0", "AngleYaw": str(yaw), "PointInfo": "1", "Gait": str(gait),
            "Speed": str(speed), "Manner": "0", "ObsMode": "0", "NavMode": "1",
            "Terrain": "0", "Posture": "0",
        }, timeout=timeout)

    def cancel(self) -> dict:
        return self.request(TYPE_NAV_CANCEL)

    def motion(self, cmd: int, value: int = -1, timeout: float = 5) -> dict:
        return self.request(2, {"Value": str(value)}, command=str(cmd), timeout=timeout)

    def init_loc(self, x: float, y: float, yaw: float = 0.0) -> dict:
        return self.request(TYPE_INIT_LOC, {
            "PosX": str(x), "PosY": str(y), "PosZ": "0", "Yaw": str(yaw)})
