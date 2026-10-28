"""短信/语音通道：向本地假网关 POST，断言收到 to/text 与签名头。"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.services.notify import _send_http


class _Ch:
    type = "sms"


class _Handler(BaseHTTPRequestHandler):
    received: dict = {}

    def log_message(self, *a):
        pass

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        _Handler.received = {
            "json": json.loads(body or b"{}"),
            "sig": self.headers.get("X-Jcrob-Signature"),
            "ts": self.headers.get("X-Jcrob-Timestamp"),
        }
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"errcode":0}')


def test_sms_payload_and_headers():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        ok, detail = _send_http(_Ch(), {"id": 1, "level": "critical", "message": "可燃气体超限",
                                        "metric": "gas"}, {"url": f"http://127.0.0.1:{port}/sms",
                                                           "to": "13800000000,13900000000"})
        assert ok, detail
        got = _Handler.received
        assert got["json"]["to"] == ["13800000000", "13900000000"]
        assert "可燃气体超限" in got["json"]["text"]
        assert got["sig"] and got["sig"].startswith("sha256=")
        assert got["ts"]
    finally:
        srv.shutdown()
