"""X30 协议解析的畸形报文容错（P1）：垃圾字节/截断/超长/未知头都不许崩。"""

from __future__ import annotations

import socket
import struct

import pytest

from app.adapters.deeprobotics import protocol as proto


def test_parse_garbage_returns_empty():
    assert proto.parse_asdu(b"not xml at all") == {}
    assert proto.parse_asdu(b"") == {}
    assert proto.parse_asdu(b"<root><Items><A>1</A></Items></root>") == {"A": "1"}


def test_parse_deep_nesting_and_entities():
    xml = b"<r><Items><X>&lt;script&gt;</X></Items></r>"
    assert proto.parse_asdu(xml)["X"] == "<script>"


def test_read_frame_rejects_unknown_magic():
    a, b = socket.socketpair()
    try:
        a.sendall(b"XXXX" + struct.pack("<HH", 4, 1) + b"\x00" * 8 + b"abcd")
        with pytest.raises(ValueError):
            proto.read_frame(b)
    finally:
        a.close()
        b.close()


def test_read_frame_rejects_absurd_length():
    a, b = socket.socketpair()
    try:
        a.sendall(proto.MAGIC_FIELD + struct.pack("<HH", 0, 1) + b"\x00" * 8)
        with pytest.raises(ValueError):
            proto.read_frame(b)
    finally:
        a.close()
        b.close()


def test_read_frame_truncated_raises_connection_error():
    a, b = socket.socketpair()
    try:
        a.sendall(proto.MAGIC_FIELD + struct.pack("<HH", 100, 1) + b"\x00" * 8 + b"short")
        a.close()
        with pytest.raises((ConnectionError, OSError)):
            proto.read_frame(b)
    finally:
        b.close()


def test_frame_roundtrip():
    asdu = proto.build_asdu(1002)
    raw = proto.frame(asdu, msg_id=7)
    assert raw[:4] == proto.MAGIC_FIELD
    assert struct.unpack("<H", raw[4:6])[0] == len(asdu)
