"""机器身份解析：X-Api-Key → 客户端信息；以及"会话或密钥"二选一依赖。"""

from __future__ import annotations

from datetime import datetime

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import PlatformError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.ai import ApiClient, hash_key


def resolve_api_client(db: Session, raw: str | None) -> dict | None:
    """返回 {"kind": "key"|"user", "name", "scopes"}；认不出来返回 None。"""
    if raw:
        c = db.query(ApiClient).filter(ApiClient.key_hash == hash_key(raw),
                                       ApiClient.enabled.is_(True)).first()
        if c is None:
            return None
        if c.expires_at is not None and c.expires_at < datetime.now():
            return None
        c.last_used_at = datetime.now()
        db.commit()
        return {"kind": "key", "name": c.name,
                "scopes": [s for s in (c.scopes or "").split(",") if s]}
    return None


def _session_user(db: Session, request: Request):
    settings = get_settings()
    token = request.cookies.get(settings.cookie_name)
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    if not token:
        return None
    from app.models.user import User

    payload = decode_access_token(token, secret=get_settings().secret_key)
    if not payload:
        return None
    return db.get(User, int(payload["sub"]))


def session_or_key(
    request: Request,
    x_api_key: str | None = Depends(lambda: None),
    db: Session = Depends(get_db),
) -> dict:
    """机器回传接口用：拿 Cookie 会话或 X-Api-Key 都行。

    机器人/算法盒不可能带 CSRF token，所以这些接口不能用写接口那套校验。
    """
    raw = request.headers.get("X-Api-Key")
    client = resolve_api_client(db, raw)
    if client is not None:
        return client
    user = _session_user(db, request)
    if user is None:
        raise PlatformError("需要登录会话或 X-Api-Key", code="UNAUTHORIZED", status_code=401)
    if getattr(user, "must_change_password", False):
        raise PlatformError("请先修改初始密码", code="MUST_CHANGE_PASSWORD", status_code=403)
    if user.role not in ("admin", "operator"):
        raise PlatformError("该接口只允许管理员/操作员或 API Key", code="FORBIDDEN",
                            status_code=403)
    return {"kind": "user", "name": user.username, "scopes": ["*"]}


def require_scope(*scopes: str):
    def dep(client: dict = Depends(session_or_key)) -> dict:
        if client["kind"] == "user":
            return client
        have = set(client["scopes"])
        if not have & set(scopes) and "*" not in have:
            raise PlatformError(f"密钥缺少权限：{' / '.join(scopes)}", code="FORBIDDEN",
                                status_code=403)
        return client
    return dep
