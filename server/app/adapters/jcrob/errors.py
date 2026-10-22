"""JCROB 侧错误码。映射见 docs/平台方案-定稿.md §5.6。

原则：HTTP 200 但业务体报错先归 BUSINESS_ERROR，不要猜成鉴权失败。
"""

from __future__ import annotations


class JcrobError(Exception):
    code = "JCROB_ERROR"
    http_status = 502

    def __init__(self, message: str, *, details: object = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class Unreachable(JcrobError):
    code = "JCROB_UNREACHABLE"
    http_status = 504


class AuthFailed(JcrobError):
    code = "JCROB_AUTH_FAILED"
    http_status = 502


class TokenIssueFailed(JcrobError):
    code = "JCROB_TOKEN_ISSUE_FAILED"
    http_status = 502


class HttpError(JcrobError):
    code = "JCROB_HTTP_ERROR"


class BusinessError(JcrobError):
    code = "JCROB_BUSINESS_ERROR"


class NotSupported(JcrobError):
    code = "JCROB_NOT_SUPPORTED"
    http_status = 501


class BusyError(JcrobError):
    code = "JCROB_BUSY"
    http_status = 409


class AuthDisabled(JcrobError):
    code = "JCROB_AUTH_DISABLED"


def is_status_ok(payload: object) -> bool:
    """PDF 里业务成功标记有 status=ok / result=true 两种写法。"""
    if isinstance(payload, dict):
        # 注意：/system/status 返回的 status 是运动模式（Free/RobotError…），不是成功标记。
        # 只把明确的失败词/错误码当失败，别把状态值当业务结果（模拟器测出来的坑）。
        status = payload.get("status")
        if isinstance(status, str) and status.lower() in {"error", "fail", "failed", "false"}:
            return False
        if "result" in payload and payload["result"] is False:
            return False
        if "success" in payload and payload["success"] is False:
            return False
        errcode = payload.get("errcode", payload.get("code"))
        if isinstance(errcode, int) and errcode != 0:
            return False
    return True
