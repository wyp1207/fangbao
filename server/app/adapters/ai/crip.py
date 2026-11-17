"""CRIP v3.8.2 开放平台适配器（192.168.1.170:8081）。

只做结果消费方：认证 → 相机/算法字典 → 告警日志分页 → 原图下载。
纪律：
1. token 只放内存，不打日志、不落盘；
2. 盒子响应常是 `Content-Type: text/plain`，按 UTF-8 → GB18030 强制解析；
3. 401/403 只自动续期一次，第二次仍失败就抛 `CripAuthError`，避免把账号打到锁；
4. 写操作不在本适配器（Phase 4 只读）。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

log = logging.getLogger(__name__)

AUTH_PATH = "/openapi/mc/v1/authenticate"
CAMERA_PATH = "/openapi/usm/v1/camera/list"
ALGORITHM_PATH = "/openapi/am/v1/algorithm/config/list"
LOG_SEARCH_PATH = "/openapi/cb/v1/log/search"

DEFAULT_TIMEOUT = 8.0


class CripError(RuntimeError):
    """适配器错误基类。"""


class CripConfigError(CripError):
    """凭据/配置缺失，不能发请求。"""


class CripUnavailable(CripError):
    """网络不可达/超时。"""


class CripAuthError(CripError):
    """认证失败或 token 失效（含 HTTP 状态码，便于联调记录）。"""

    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.status_code = status_code


class CripHttpError(CripError):
    """盒子返回非 2xx（401/403 以外）。"""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class CripProtocolError(CripError):
    """响应不是可解析的 JSON / 缺少必要字段。"""


@dataclass(frozen=True)
class LogPage:
    records: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True)
class ImageResult:
    status_code: int
    content: bytes
    content_type: str


def absolute_url(url: str | None, base_url: str) -> str:
    """盒子给的是相对路径（/dw/...），拼上盒子地址。已是绝对地址就原样返回。"""
    value = (url or "").strip()
    base = base_url.rstrip("/")
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    return f"{base}/{value.lstrip('/')}"


def _as_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _fmt_dt(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


class CripClient:
    """一个盒子一个实例；token 在实例内存里复用。"""

    def __init__(
        self,
        base_url: str,
        app_id: str,
        app_secret: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not base_url:
            raise CripConfigError("缺少盒子地址 base_url")
        if not app_id or not app_secret:
            raise CripConfigError("缺少 app_id / app_secret")
        self.base_url = base_url.rstrip("/")
        self._app_id = app_id
        self._app_secret = app_secret
        self._timeout = timeout
        self._client = http_client or httpx.Client(
            timeout=httpx.Timeout(timeout, connect=3.0), follow_redirects=True
        )
        self._owns_client = http_client is None
        self._token: str | None = None

    @classmethod
    def from_env(
        cls,
        base_url: str,
        *,
        prefix: str = "AI170",
        timeout: float = DEFAULT_TIMEOUT,
        http_client: httpx.Client | None = None,
    ) -> "CripClient":
        """凭据只从环境变量读；缺失时明确报错，不用默认口令兜底。"""
        app_id = os.environ.get(f"{prefix}_APP_ID", "").strip()
        app_secret = os.environ.get(f"{prefix}_APP_SECRET", "").strip()
        missing = [f"{prefix}_{name}" for name, value in
                   (("APP_ID", app_id), ("APP_SECRET", app_secret)) if not value]
        if missing:
            raise CripConfigError("缺少环境变量 " + " / ".join(missing))
        return cls(base_url, app_id, app_secret, timeout=timeout, http_client=http_client)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "CripClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ---------- 内部：URL / 解析 / 发送 ----------

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return absolute_url(path, self.base_url)

    def _decode(self, resp: httpx.Response) -> Any:
        """盒子用 text/plain 返回 JSON；UTF-8 失败再回退 GB18030。"""
        raw = resp.content
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                text = raw.decode(encoding)
            except UnicodeDecodeError:
                continue
            try:
                return json.loads(text)
            except ValueError:
                continue
        raise CripProtocolError(
            f"{resp.request.url.path} 返回不是 JSON（{len(raw)} 字节）"
        )

    def _auth_header(self) -> str:
        token = self._token or ""
        if token.lower().startswith("bearer "):
            return token
        return f"Bearer {token}"

    def _send(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        retry_auth: bool = True,
    ) -> httpx.Response:
        try:
            resp = self._client.request(
                method,
                url,
                params=params,
                json=json_body,
                headers={"Authorization": self._auth_header()},
            )
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
            raise CripUnavailable(f"{method} {url} 不可达: {exc.__class__.__name__}") from exc
        except httpx.HTTPError as exc:  # pragma: no cover - 兜底
            raise CripUnavailable(f"{method} {url} 失败: {exc.__class__.__name__}") from exc

        if resp.status_code in (401, 403):
            if retry_auth:
                # token 可能过期：清掉内存 token，续期后只重试一次
                self._token = None
                self.authenticate()
                return self._send(method, url, params=params, json_body=json_body,
                                  retry_auth=False)
            raise CripAuthError(
                f"{method} {url} -> HTTP {resp.status_code}", status_code=resp.status_code
            )
        if resp.status_code >= 400:
            raise CripHttpError(
                f"{method} {url} -> HTTP {resp.status_code}", status_code=resp.status_code
            )
        return resp

    def _ensure_token(self) -> None:
        if not self._token:
            self.authenticate()

    def _request_json(
        self, method: str, path: str, *, params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> dict[str, Any]:
        self._ensure_token()
        resp = self._send(method, self._url(path), params=params, json_body=json_body)
        payload = self._decode(resp)
        if not isinstance(payload, dict):
            raise CripProtocolError(f"{path} 响应顶层不是对象")
        return payload

    # ---------- 认证 ----------

    def authenticate(self) -> str:
        """POST /openapi/mc/v1/authenticate，token 只存内存。"""
        url = self._url(AUTH_PATH)
        try:
            resp = self._client.post(
                url, json={"app_id": self._app_id, "app_secret": self._app_secret}
            )
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
            raise CripUnavailable(
                f"认证不可达: {exc.__class__.__name__}"
            ) from exc
        except httpx.HTTPError as exc:  # pragma: no cover - 兜底
            raise CripUnavailable(f"认证失败: {exc.__class__.__name__}") from exc

        if resp.status_code in (401, 403):
            raise CripAuthError(
                f"认证被拒: HTTP {resp.status_code}", status_code=resp.status_code
            )
        if resp.status_code >= 400:
            raise CripHttpError(
                f"认证失败: HTTP {resp.status_code}", status_code=resp.status_code
            )

        payload = self._decode(resp)
        token = ""
        if isinstance(payload, dict):
            token = str(payload.get("accessToken") or payload.get("access_token") or "")
            data = payload.get("data")
            if not token and isinstance(data, dict):
                token = str(data.get("accessToken") or data.get("access_token") or "")
        if not token:
            raise CripAuthError("认证响应没有 accessToken", status_code=resp.status_code)

        self._token = token
        # 只记长度和前缀类型，绝不打印 token 本身
        log.info("CRIP 认证成功 base=%s token_len=%s", self.base_url, len(token))
        return token

    # ---------- 字典 ----------

    def list_cameras(self, page_size: int = 50) -> list[dict[str, Any]]:
        payload = self._request_json(
            "GET", CAMERA_PATH, params={"current": 1, "page_size": page_size}
        )
        rows = payload.get("data")
        if isinstance(rows, dict):
            rows = rows.get("list") or rows.get("records") or rows.get("items") or []
        result = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            result.append({
                "id": _as_int(row.get("id")),
                "camera_id": row.get("camera_id"),
                "name": row.get("name") or "",
                "online_status": _as_int(row.get("online_status")),
                "stream_url": row.get("stream_url") or "",
            })
        return result

    def list_algorithms(self, page_size: int = 100) -> list[dict[str, Any]]:
        payload = self._request_json(
            "GET", ALGORITHM_PATH, params={"current": 1, "page_size": page_size}
        )
        rows = payload.get("data")
        if isinstance(rows, dict):
            rows = rows.get("list") or rows.get("records") or rows.get("items") or []
        result = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            default = row.get("default_info") or {}
            result.append({
                "algorithm_id": _as_int(row.get("algorithm_id")),
                "name": row.get("name") or default.get("name") or "",
                "name_en": row.get("name_en") or default.get("name_en") or "",
                "degree": _as_int(row.get("degree", default.get("degree"))),
            })
        return result

    # ---------- 告警日志 ----------

    def search_logs(
        self,
        start: datetime | str,
        end: datetime | str,
        page: int = 1,
        page_size: int = 100,
        *,
        log_type: str = "video",
    ) -> LogPage:
        """POST /openapi/cb/v1/log/search。分页字段是 current，不是 page。"""
        body = {
            "current": max(1, int(page)),
            "page_size": max(1, int(page_size)),
            "start_date": _fmt_dt(start),
            "end_date": _fmt_dt(end),
            "log_type": log_type,
        }
        payload = self._request_json("POST", LOG_SEARCH_PATH, json_body=body)
        rows = payload.get("data")
        if isinstance(rows, dict):
            rows = rows.get("list") or rows.get("records") or rows.get("items") or []
        records = [row for row in (rows or []) if isinstance(row, dict)]
        return LogPage(
            records=records,
            total=_as_int(payload.get("total"), 0) or 0,
            page=_as_int(payload.get("current"), body["current"]) or body["current"],
            page_size=_as_int(payload.get("page_size"), body["page_size"]) or body["page_size"],
        )

    # ---------- 图片 ----------

    def download_image(self, url: str) -> ImageResult:
        """GET 盒子图片 URL，带 Bearer；401/403 续期后重试一次。

        返回状态码而不是 bool：Phase 4 要记录“图片是否需要鉴权、实际返回什么”。
        """
        self._ensure_token()
        full = self._url(url)
        resp = self._send("GET", full)
        return ImageResult(
            status_code=resp.status_code,
            content=resp.content,
            content_type=resp.headers.get("content-type", ""),
        )
