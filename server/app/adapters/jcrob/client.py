"""JCROB HTTP 客户端：token、超时、错误映射、URL 编码。

三条纪律：
1. URL 按 PDF 原文，空格编码成 %20（`/navigation/move to index` 不改名）；
2. 写操作永不自动重试（本层只提供 get/post_raw，重试策略由 CommandGateway 决定）；
3. 任何日志/异常里的 URL 都过 redaction，token 不进日志。
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from app.core.redaction import redact_url
from app.adapters.jcrob import errors as jerr

log = logging.getLogger(__name__)

API_PREFIX = "/api/v1"
_SAFE_PATH = "/"


def encode_path(path: str) -> str:
    """`/navigation/move to index` -> `/navigation/move%20to%20index`。"""
    return quote(path if path.startswith("/") else f"/{path}", safe=_SAFE_PATH)


class JcrobHttpClient:
    def __init__(self, base_url: str, *, token: str = "", timeout: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._timeout = timeout
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=1.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    def _url(self, path: str, params: dict[str, Any] | None) -> str:
        url = f"{self.base_url}{API_PREFIX}{encode_path(path)}"
        query = dict(params or {})
        if self.token:
            query["token"] = self.token
        if query:
            url = f"{url}?{urlencode(query)}"
        return url

    async def _request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None,
        json_body: Any = None, raw: bool = False,
    ) -> Any:
        url = self._url(path, params)
        try:
            resp = await self._client.request(method, url, json=json_body)
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
            raise jerr.Unreachable(f"{method} {redact_url(url)} 不可达: {exc}") from exc
        except httpx.HTTPError as exc:  # pragma: no cover - 兜底
            raise jerr.HttpError(f"{method} {redact_url(url)} 失败: {exc}") from exc

        if resp.status_code in (401, 403):
            raise jerr.AuthFailed(
                f"{method} {redact_url(url)} -> HTTP {resp.status_code}",
                details=resp.text[:200],
            )
        if resp.status_code >= 400:
            raise jerr.HttpError(
                f"{method} {redact_url(url)} -> HTTP {resp.status_code}",
                details=resp.text[:200],
            )
        if raw:
            return resp.content
        try:
            payload = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise jerr.HttpError(
                f"{method} {redact_url(url)} 返回不是 JSON",
                details=resp.text[:200],
            ) from exc
        if not jerr.is_status_ok(payload):
            raise jerr.BusinessError(
                f"{method} {path} 业务失败", details=payload if isinstance(payload, dict) else None
            )
        return payload

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, json_body: Any = None) -> Any:
        return await self._request("POST", path, json_body=json_body)

    async def request(self, method: str, path: str, json_body: Any = None) -> Any:
        return await self._request(method, path, json_body=json_body)

    async def get_bytes(self, path: str, params: dict[str, Any] | None = None) -> bytes:
        return await self._request("GET", path, params=params, raw=True)

    async def get_bytes_url(self, url: str) -> bytes:
        """抓拍返回的是完整 URL（可能不带 token）：直接 GET 一次。"""
        try:
            resp = await self._client.get(url)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise jerr.Unreachable(f"抓拍下载不可达: {exc}") from exc
        if resp.status_code >= 400:
            raise jerr.HttpError(f"抓拍下载 HTTP {resp.status_code}")
        return resp.content

    async def get_bytes_path(self, path: str) -> bytes:
        """抓拍返回的是机器人本地文件路径：走后端文件读取接口。"""
        params = {"path": path}
        if self.token:
            params["token"] = self.token
        url = f"{self.base_url}{API_PREFIX}/file"
        try:
            resp = await self._client.get(url, params=params)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise jerr.Unreachable(f"文件读取不可达: {exc}") from exc
        if resp.status_code >= 400:
            raise jerr.HttpError(f"文件读取 HTTP {resp.status_code}", details=resp.text[:120])
        return resp.content

    async def fetch_token(self, username: str, password: str) -> str:
        """GET /token?username=&password=（PDF p8）。

        密码在 query 里，所以这条路径的 URL 只能进脱敏日志。
        返回 result:false 归 TOKEN_ISSUE_FAILED，不代表已有 token 过期。
        """
        url = f"{self.base_url}{API_PREFIX}/token"
        try:
            resp = await self._client.get(
                url, params={"username": username, "password": password}
            )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise jerr.Unreachable(f"/token 不可达: {exc}") from exc
        if resp.status_code in (401, 403):
            raise jerr.AuthFailed(f"/token -> HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise jerr.HttpError(f"/token -> HTTP {resp.status_code}", details=resp.text[:200])
        try:
            payload = resp.json()
        except ValueError as exc:
            raise jerr.TokenIssueFailed("/token 返回不是 JSON") from exc
        token = payload.get("token") or payload.get("access_token") or ""
        if not token:
            raise jerr.TokenIssueFailed("/token 没返回 token 字段", details=payload)
        self.token = token
        return token
