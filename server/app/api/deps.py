"""FastAPI 依赖：当前用户、角色、CSRF。"""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Forbidden, PlatformError, Unauthorized
from app.core.security import csrf_matches, decode_access_token
from app.db.session import get_db
from app.models.user import User


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    settings = get_settings()
    token = request.cookies.get(settings.cookie_name)
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise Unauthorized("未登录")
    try:
        payload = decode_access_token(token, secret=settings.secret_key)
    except Exception as exc:  # noqa: BLE001 - 过期/篡改统一按未登录处理
        raise Unauthorized("登录已过期") from exc

    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise Unauthorized("账号不可用")
    _enforce_password_change(request, user)
    return user


# 初始密码没改之前，只允许这几个接口
_PWD_CHANGE_ALLOWED = ("/auth/password", "/auth/me", "/auth/logout", "/auth/login")


def _enforce_password_change(request: Request, user: User) -> None:
    """后端也要拦：只靠前端弹窗，绕过前端直接调接口就形同虚设。"""
    if not getattr(user, "must_change_password", False):
        return
    path = request.url.path
    if any(path.endswith(p) for p in _PWD_CHANGE_ALLOWED):
        return
    raise PlatformError("请先修改初始密码再使用平台", code="MUST_CHANGE_PASSWORD",
                        status_code=403)


def require_roles(*roles: str):
    def _dep(user: User = Depends(get_current_user)) -> User:
        if roles and user.role not in roles:
            raise Forbidden(f"需要角色 {'/'.join(roles)}")
        return user

    return _dep


def require_csrf(request: Request) -> None:
    """写接口的 CSRF：双提交 Cookie（cookie 与 header 必须一致）。"""
    settings = get_settings()
    cookie = request.cookies.get(settings.csrf_cookie)
    header = request.headers.get("X-CSRF-Token")
    if not csrf_matches(cookie, header):
        raise Forbidden("CSRF 校验失败", code="CSRF_FAILED")


# 运行时单例都挂在 app.state 上，这里只做取值，不新建文件
def get_adapter(request: Request):
    return request.app.state.adapter


def get_cache(request: Request):
    return request.app.state.cache


def get_services(request: Request):
    return request.app.state.services


def get_alarms(request: Request):
    return request.app.state.alarms
