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
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s")
    handlers: list[logging.Handler] = []

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    stream.addFilter(RedactFilter())
    handlers.append(stream)

    # 落盘：容器里 /app/logs 已挂卷；按天轮转，保留 180 天（等保 6 个月）
    import os
    from logging.handlers import TimedRotatingFileHandler

    log_dir = os.environ.get("JC_LOG_DIR", "/app/logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            os.path.join(log_dir, "app.log"), when="midnight",
            backupCount=int(os.environ.get("JC_LOG_BACKUP_DAYS", "180")),
            encoding="utf-8", utc=False,
        )
        file_handler.suffix = "%Y-%m-%d"
        file_handler.setFormatter(fmt)
        file_handler.addFilter(RedactFilter())
        handlers.append(file_handler)
    except OSError:
        # 只读文件系统/没权限时退回 stdout，不要让平台起不来
        pass

    root = logging.getLogger()
    root.handlers = handlers
    root.setLevel(level.upper())
    # httpx 的请求日志自带完整 URL，降级到 WARNING，避免 token 入日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
