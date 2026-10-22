"""云深处 X30 本体监控协议（TCP 30000）的帧编解码。

协议依据官方文档《本体监控协议（TCP）》：
- 16 字节头：EB 91 EB 90 + 长度(u16 LE) + 报文ID(u16 LE) + 8 字节 0
- ASDU 是 XML：<PatrolDevice><Type/><Command/><Time/><Items/></PatrolDevice>

只做"读写一帧"这一件事，业务映射放在 adapter 里。
"""

from __future__ import annotations

import socket
import struct
import time
from datetime import datetime

MAGIC = b"\xeb\x91\xeb\x90"
HEADER_LEN = 16

# 官方消息类型
TYPE_STATUS = 1002       # 实时基础状态
TYPE_NAV_TASK = 1003     # 下发导航任务
TYPE_NAV_CANCEL = 1004   # 取消导航任务
TYPE_NAV_QUERY = 1007    # 导航任务状态
TYPE_BATTERY = 2001      # 电池信息
TYPE_INIT_LOC = 2101     # 初始化定位


def build_asdu(msg_type: int, command: int = 1, items: str = "") -> bytes:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><PatrolDevice>'
           f'<Type>{msg_type}</Type><Command>{command}</Command>'
           f'<Time>{ts}</Time><Items>{items}</Items></PatrolDevice>')
    return xml.encode("utf-8")


def frame(asdu: bytes, msg_id: int) -> bytes:
    return MAGIC + struct.pack("<HH", len(asdu), msg_id & 0xFFFF) + b"\x00" * 8 + asdu


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("连接被关闭")
        buf += chunk
    return buf


def read_frame(sock: socket.socket) -> bytes:
    """读一帧，返回 ASDU 原始字节（XML）。"""
    head = _recv_exact(sock, HEADER_LEN)
    if head[:4] != MAGIC:
        raise ValueError(f"协议头不对: {head[:4].hex()}")
    length, _msg_id = struct.unpack("<HH", head[4:8])
    if length <= 0 or length > 65535:
        raise ValueError(f"长度异常: {length}")
    return _recv_exact(sock, length)


class X30Client:
    """一次请求一个响应。短连接更稳：机器人掉线时不至于卡住一个长连接。"""

    def __init__(self, host: str, port: int = 30000, timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._msg_id = 0

    def request(self, msg_type: int, command: int = 1, items: str = "") -> bytes:
        asdu = build_asdu(msg_type, command, items)
        self._msg_id = (self._msg_id + 1) & 0xFFFF
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.settimeout(self.timeout)
            sock.sendall(frame(asdu, self._msg_id))
            return read_frame(sock)

    def query_status(self) -> str:
        return self.request(TYPE_STATUS).decode("utf-8", "replace")

    def query_battery(self) -> str:
        return self.request(TYPE_BATTERY).decode("utf-8", "replace")

    def query_task(self) -> str:
        return self.request(TYPE_NAV_QUERY).decode("utf-8", "replace")
