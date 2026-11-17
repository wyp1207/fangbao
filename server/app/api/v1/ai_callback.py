"""AI 回调接收端：边缘盒子把原始 payload 推过来，平台只落盘，不做映射。

为什么单独一个入口、且不写库：盒子侧回调格式随算法/固件变，本轮先"原样收、
带时间戳和脱敏后的请求头存下来"，等拿到真实 payload 再决定怎么映射到 ai_result
和告警。所以这里刻意不写 ai_result、不建告警、不校验业务字段。

鉴权用共享令牌（env ``AI_CALLBACK_TOKEN``），不走登录/CSRF：盒子拿不到浏览器
会话。没配令牌就一律拒绝（fail-closed），避免"忘了配 = 人人可写盘"。

落盘：``data/ai_callbacks/<YYYYMMDD>/<uuid>.json``，先写临时文件再原子替换，
保证平台重启/写满盘时不会留下半截 JSON。
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from app.core.errors import PlatformError, Unauthorized
from app.core.redaction import MASK, redact_obj

log = logging.getLogger(__name__)

router = APIRouter(prefix="/ai/callback", tags=["ai-callback"])

ROOT = Path(__file__).resolve().parents[3] / "data" / "ai_callbacks"
MAX_BODY_BYTES = 2 * 1024 * 1024
TOKEN_ENV = "AI_CALLBACK_TOKEN"
TOKEN_HEADER = "X-Callback-Token"
# 这几个头不看 key 名也要盖掉：Authorization/Cookie 里可能有会话凭据
_ALWAYS_MASK_HEADERS = ("authorization", "proxy-authorization", "cookie", "set-cookie")


class PayloadTooLarge(PlatformError):
    status_code = 413
    code = "CALLBACK_TOO_LARGE"


def _expected_token() -> str:
    return os.environ.get(TOKEN_ENV, "").strip()


def _require_token(request: Request, token: str | None) -> None:
    expected = _expected_token()
    if not expected:
        # 没配置就不要猜：宁可直接拒绝，也不要变成开放写入
        log.warning("%s 未配置，AI 回调请求已拒绝（fail-closed）", TOKEN_ENV)
        raise Unauthorized("回调令牌未配置，已拒绝", code="CALLBACK_TOKEN_NOT_CONFIGURED")
    supplied = (token or request.headers.get(TOKEN_HEADER) or "").strip()
    if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise Unauthorized("回调令牌缺失或错误", code="CALLBACK_TOKEN_INVALID")


async def _read_body(request: Request) -> bytes:
    """边读边计数：Content-Length 声明超限直接拒，没声明也不能被流式灌爆。"""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise PayloadTooLarge(f"payload 超过 {MAX_BODY_BYTES} 字节")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            raise PayloadTooLarge(f"payload 超过 {MAX_BODY_BYTES} 字节")
        chunks.append(chunk)
    return b"".join(chunks)


def _redacted_headers(request: Request) -> dict[str, Any]:
    raw = {k.lower(): v for k, v in request.headers.items()}
    out = redact_obj(raw)          # token/password/secret/... 这类 key 直接 ***
    for name in _ALWAYS_MASK_HEADERS:
        if name in out:
            out[name] = MASK
    return out


def _decode_body(raw: bytes) -> Any:
    """JSON 就存 JSON，别的按文本存；空 body 存 None。"""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return raw.decode("utf-8", "replace")


def _save(source_key: str, headers: dict[str, Any], raw: bytes) -> tuple[str, Path]:
    now = datetime.now().astimezone()
    ident = uuid.uuid4().hex
    directory = ROOT / now.strftime("%Y%m%d")
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "id": ident,
        "source_key": source_key,
        "received_at": now.isoformat(timespec="milliseconds"),
        "headers": headers,
        "body": _decode_body(raw),
    }
    path = directory / f"{ident}.json"
    tmp = directory / f".{ident}.json.tmp"
    try:
        tmp.write_bytes(json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8"))
        os.replace(tmp, path)      # 原子替换，读端不会看到半截 JSON
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    return ident, path


@router.get("/ping")
def ping() -> dict:
    """盒子/浏览器连通性自检：只回 ok，不暴露任何配置。"""
    return {"ok": True}


@router.post("/{source_key}")
async def receive_callback(source_key: str, request: Request, token: str | None = None) -> dict:
    _require_token(request, token)          # 先鉴权，别为无效请求浪费 IO
    raw = await _read_body(request)
    ident, _path = _save(source_key, _redacted_headers(request), raw)
    # 先落盘再回 200：盒子收到成功才会删本地队列
    return {"ok": True, "id": ident, "bytes": len(raw)}
