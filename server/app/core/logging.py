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


class AccessRedactFilter(logging.Filter):
    """uvicorn access 记录的脱敏。

    这条链上的 formatter（uvicorn.logging.AccessFormatter）直接解包
    ``record.args`` 的 5 项来拼 request_line，所以只能替换 args[2]（full_path），
    不能像 RedactFilter 那样把整行塞进 record.msg —— 那样 formatter 会抛
    ValueError，整条访问日志直接丢失。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            client_addr, method, full_path, http_version, status_code = args
            record.args = (client_addr, method, redact_text(full_path),
                           http_version, status_code)
        return True


def install_request_log_redaction() -> None:
    """给 uvicorn 自己的 logger 补上脱敏。

    uvicorn 的 access/error logger 由它自己的 dictConfig 配 handler 且
    propagate=False，root handler 上的 RedactFilter 管不到它们，于是
    `?token=...` 会原样写进访问日志——这正是本模块开头那句
    "token/password 不进任何一行日志" 的破口（AI 回调就用 query token）。
    """
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, AccessRedactFilter) for f in access.filters):
        access.addFilter(AccessRedactFilter())
    for name in ("uvicorn.error", "uvicorn"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactFilter) for f in logger.filters):
            logger.addFilter(RedactFilter())


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
    install_request_log_redaction()
