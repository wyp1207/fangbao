"""平台错误模型。

两条线：
- PlatformError：平台自己的错误，带 HTTP 状态码与稳定 code；
- JCROB_* ：机器人侧错误，见 adapters/jcrob/errors.py，最终都包装成 PlatformError。
"""

from __future__ import annotations

from typing import Any


class PlatformError(Exception):
    status_code: int = 400
    code: str = "PLATFORM_ERROR"

    def __init__(self, message: str, *, code: str | None = None,
                 status_code: int | None = None, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            body["details"] = self.details
        return body


class NotFound(PlatformError):
    status_code = 404
    code = "NOT_FOUND"


class Unauthorized(PlatformError):
    status_code = 401
    code = "UNAUTHORIZED"


class Forbidden(PlatformError):
    status_code = 403
    code = "FORBIDDEN"


class Conflict(PlatformError):
    status_code = 409
    code = "CONFLICT"


class BadRequest(PlatformError):
    status_code = 400
    code = "BAD_REQUEST"


class ExternalUnavailable(PlatformError):
    status_code = 503
    code = "EXTERNAL_UNAVAILABLE"
