"""统一脱敏：日志、URL、异常、落盘 JSON 都过这里。

与 scripts/probe_jcrob.py 的 SENSITIVE_KEY_RE 保持一致；Probe 是离线工具，
这里是运行时唯一实现。CONFIG_VIEW_FIELDS 见 adapters/jcrob/config_view.py。
"""

from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|pwd|secret|token|credential|ssid|wifi|private_key|api_?key)",
    re.IGNORECASE,
)

# URL / 文本里的凭据：token=xxx、password=xxx&...
_TEXT_SECRET_RE = re.compile(
    r"((?:token|password|passwd|pwd|secret|access_token)=)[^&\s\"']+",
    re.IGNORECASE,
)

MASK = "***"


def redact_text(text: str) -> str:
    return _TEXT_SECRET_RE.sub(rf"\1{MASK}", text)


def redact_url(url: str) -> str:
    return redact_text(url)


def redact_obj(value: Any) -> Any:
    """递归：保留 key，敏感值替换成 ***。"""
    if isinstance(value, dict):
        return {
            k: (MASK if SENSITIVE_KEY_RE.search(str(k)) else redact_obj(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_obj(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
