"""日志：统一脱敏 + 简单格式。token/password 不进任何一行日志。"""

from __future__ import annotations

import logging
import sys

from app.core.redaction import redact_text

_REQUIRED = ("token", "password", "passwd", "secret")


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        cleaned = redact_text(msg)
        if cleaned != msg:
            record.msg = cleaned
            record.args = ()
        return True


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s")
    )
    handler.addFilter(RedactFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # httpx 的请求日志自带完整 URL，降级到 WARNING，避免 token 入日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
