"""AI 回调接收端：边缘盒子把真实 payload 推过来 → 原始 JSON 落盘 → 归一化入库。

两层职责分开，顺序不能反：
1. 先把原始 body 原样落盘（``data/ai_callbacks/<YYYYMMDD>/<uuid>.json``）；
2. 再调 ``ai_callback_ingest.ingest`` 归一化写 ``ai_result``，并按事件日下载
   证据图。入库/下载失败只记日志、回 200 且 ``ingested=false``——盒子收到非 2xx
   会一直重推，原始 payload 已经落盘，没必要把回调打成失败。

下载放在线程池里跑（超时 5s）：ingest 是同步阻塞代码，直接在 async 入口里跑会
把事件循环一起卡住，慢盒子会拖死所有接口。

入库成功后由 `ai_alarm.evaluate` 按 P1/P2 规则建告警（只认机器人相机，带 60s
去重）；告警失败只记日志，不影响回调返回 200。

鉴权用共享令牌（env ``AI_CALLBACK_TOKEN``），不走登录/CSRF：盒子拿不到浏览器
会话。没配令牌就一律拒绝（fail-closed），避免"忘了配 = 人人可写盘"。
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
from starlette.concurrency import run_in_threadpool

from app.core.errors import PlatformError, Unauthorized
from app.core.redaction import MASK, redact_obj
from app.services import ai_callback_ingest

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


def _ingest(body: Any) -> dict[str, Any]:
    """在自己的 session 里跑：这个函数会被丢进线程池，不能复用请求线程的会话。"""
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        return ai_callback_ingest.ingest(db, body)


@router.get("/ping")
def ping() -> dict:
    """盒子/浏览器连通性自检：只回 ok，不暴露任何配置。"""
    return {"ok": True}


@router.post("/{source_key}")
async def receive_callback(source_key: str, request: Request, token: str | None = None) -> dict:
    _require_token(request, token)          # 先鉴权，别为无效请求浪费 IO
    raw = await _read_body(request)
    ident, _path = _save(source_key, _redacted_headers(request), raw)
    # 先落盘再入库：入库失败也不会丢盒子推过来的原始 payload
    body = _decode_body(raw)
    try:
        result = await run_in_threadpool(_ingest, body)
    except Exception:  # noqa: BLE001 - 入库失败不能把回调打成非 2xx
        log.exception("AI 回调入库失败 id=%s（原始 payload 已落盘）", ident)
        result = {"ingested": False, "skipped": False, "duplicate": False,
                  "result_id": None, "image_ok": False}
    # 盒子收到 200 才会删本地队列
    return {
        "ok": True,
        "id": ident,
        "bytes": len(raw),
        "ingested": bool(result.get("ingested")),
        "skipped": bool(result.get("skipped")),
        "duplicate": bool(result.get("duplicate")),
        "result_id": result.get("result_id"),
        "image": bool(result.get("image_ok")),
    }

