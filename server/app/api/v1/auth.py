from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_csrf
from app.core.config import get_settings


def _cookie_secure(request: Request, settings) -> bool:
    """部署在 http 内网时不能给 cookie 加 Secure，否则浏览器不回传。"""
    if settings.cookie_secure is not None:
        return bool(settings.cookie_secure)
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").lower()
    return proto == "https"
from app.core.errors import BadRequest, PlatformError, Unauthorized
import time

from app.core.security import (create_access_token, hash_password, new_csrf_token,
                               totp_code, totp_secret, totp_uri, totp_verify, totp_verify_step,
                               validate_password, verify_password)
from app.db.session import get_db
from app.services.messages import audit
from app.models.user import User


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None

router = APIRouter(prefix="/auth", tags=["auth"])

# 登录防爆破：连续失败 5 次锁 10 分钟。落库，重启不清零
LOGIN_MAX_FAIL = 5
LOGIN_LOCK_MIN = 10
PASSWORD_HISTORY = 5


def _attempt_key(username: str, ip: str | None) -> str:
    return f"{username.lower()}|{ip or '-'}"


def _locked_seconds(db: Session, key: str) -> int:
    from app.models.user import LoginAttempt

    row = db.scalar(select(LoginAttempt).where(LoginAttempt.key == key))
    if row is None or row.locked_until is None:
        return 0
    left = int((row.locked_until - datetime.now()).total_seconds())
    if left <= 0:
        row.locked_until = None
        row.fails = 0
        db.commit()
        return 0
    return left


def _record_fail(db: Session, key: str) -> None:
    """失败的账号不管存不存在都计数：否则爆破不存在的用户名永远不锁。"""
    from app.models.user import LoginAttempt

    row = db.scalar(select(LoginAttempt).where(LoginAttempt.key == key))
    if row is None:
        row = LoginAttempt(key=key, fails=0)
        db.add(row)
    row.fails = (row.fails or 0) + 1
    row.updated_at = datetime.now()
    if row.fails >= LOGIN_MAX_FAIL:
        row.locked_until = datetime.now() + timedelta(minutes=LOGIN_LOCK_MIN)
        row.fails = 0
    db.commit()


def _clear_fail(db: Session, key: str) -> None:
    from app.models.user import LoginAttempt

    row = db.scalar(select(LoginAttempt).where(LoginAttempt.key == key))
    if row is not None:
        row.fails = 0
        row.locked_until = None
        db.commit()


def _record_password(db: Session, user: User, plain: str) -> None:
    """记录新密码哈希，并裁剪到最近 5 条。"""
    from app.models.user import PasswordHistory

    db.add(PasswordHistory(user_id=user.id, password_hash=hash_password(plain)))
    rows = (db.query(PasswordHistory)
            .filter(PasswordHistory.user_id == user.id)
            .order_by(PasswordHistory.id.desc()).all())
    for old in rows[PASSWORD_HISTORY:]:
        db.delete(old)
    user.password_changed_at = datetime.now()
    db.commit()


def _reused_password(db: Session, user: User, plain: str) -> bool:
    from app.models.user import PasswordHistory

    rows = (db.query(PasswordHistory)
            .filter(PasswordHistory.user_id == user.id)
            .order_by(PasswordHistory.id.desc()).limit(PASSWORD_HISTORY).all())
    return any(verify_password(plain, r.password_hash) for r in rows)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    totp_code: str | None = None          # 开了双因子的账号必须带


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    must_change_password: bool = False


class LoginOut(BaseModel):
    user: UserOut
    csrf_token: str


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, response: Response, request: Request,
          db: Session = Depends(get_db)) -> LoginOut:
    settings = get_settings()
    key = _attempt_key(body.username, request.client.host if request.client else None)
    left = _locked_seconds(db, key)
    if left:
        raise Unauthorized(f"登录失败次数过多，请 {left // 60 + 1} 分钟后再试")

    user = db.scalar(select(User).where(User.username == body.username))
    if user and user.totp_enabled and user.is_active and verify_password(body.password, user.password_hash):
        if not body.totp_code:
            raise PlatformError("该账号已开启双因子，请输入动态码", code="TOTP_REQUIRED",
                                status_code=401)
        step = totp_verify_step(user.totp_secret or "", body.totp_code)
        if step is None:
            raise PlatformError("动态码不正确", code="TOTP_INVALID", status_code=401)
        # 防重放：同一个 30s 窗内的码用过就不能再用
        if user.totp_last_step is not None and step <= user.totp_last_step:
            raise PlatformError("动态码已使用过，请等下一个", code="TOTP_REPLAY",
                                status_code=401)
        user.totp_last_step = step
        db.commit()

    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        _record_fail(db, key)
        from app.services.messages import store as msg_store

        msg_store.add("warn", "user", f"登录失败：{body.username}",
                      "账号不存在、已停用或密码错误" if user else "账号不存在",
                      {"to": "users"} if user else {})
        # 失败登录也要进审计（等保要求的"登录事件可追溯"）
        audit(db=db, action="auth.login_failed", target=body.username, user=None,
              client_ip=_ip(request), summary="登录失败")
        raise Unauthorized("用户名或密码错误")

    _clear_fail(db, key)              # 登录成功清零

    audit(db=db, action="auth.login", target=user.username, user=user,
          client_ip=_ip(request), summary="登录成功")

    token = create_access_token(
        str(user.id), user.role, secret=settings.secret_key,
        ttl_minutes=settings.jwt_ttl_minutes,
        extra={"ver": int(user.token_version or 1)},
    )
    csrf = new_csrf_token()
    secure = _cookie_secure(request, settings)
    response.set_cookie(
        settings.cookie_name, token, httponly=True, samesite="lax",
        secure=secure, max_age=settings.jwt_ttl_minutes * 60, path="/",
    )
    response.set_cookie(
        settings.csrf_cookie, csrf, httponly=False, samesite="lax",
        secure=secure, max_age=settings.jwt_ttl_minutes * 60, path="/",
    )
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return LoginOut(user=UserOut(id=user.id, username=user.username, role=user.role,
                                 must_change_password=bool(user.must_change_password)),
                    csrf_token=csrf)


@router.post("/logout")
def logout(response: Response, request: Request,
           db: Session = Depends(get_db)) -> dict:
    """登出 = 服务端吊销：把 token_version +1，旧 token 立刻不能再用。

    只删 Cookie 是不够的——token 被复制走之后照样能用到过期。
    """
    from app.core.security import decode_access_token
    from app.models.user import User as _User

    settings = get_settings()
    token = request.cookies.get(settings.cookie_name)
    if token:
        payload = decode_access_token(token, secret=settings.secret_key)
        if payload and payload.get("sub"):
            u = db.get(_User, int(payload["sub"]))
            if u is not None:
                u.token_version = int(u.token_version or 1) + 1
                db.commit()
    response.delete_cookie(settings.cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(id=user.id, username=user.username, role=user.role,
                   must_change_password=bool(user.must_change_password))


class PasswordChange(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


@router.post("/password", dependencies=[Depends(require_csrf)])
def change_own_password(
    body: PasswordChange,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """用户自助改密：必须验旧密码。管理员重置走 /users/{id}/password。"""
    if not verify_password(body.old_password, user.password_hash):
        raise Unauthorized("原密码不正确")
    if body.old_password == body.new_password:
        raise Unauthorized("新密码不能和原密码相同")
    try:
        validate_password(body.new_password, username=user.username)
    except ValueError as exc:
        raise BadRequest(str(exc), code="WEAK_PASSWORD") from exc

    if _reused_password(db, user, body.new_password):
        raise BadRequest(f"不能重复使用最近 {PASSWORD_HISTORY} 次用过的密码",
                         code="PASSWORD_REUSED")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.token_version = int(user.token_version or 1) + 1
    _record_password(db, user, body.new_password)
    db.commit()
    # 改密会让所有旧会话失效——但当前这个会话要给新 token，否则用户被自己踢下线
    settings = get_settings()
    token = create_access_token(
        str(user.id), user.role, secret=settings.secret_key,
        ttl_minutes=settings.jwt_ttl_minutes, extra={"ver": int(user.token_version or 1)},
    )
    secure = _cookie_secure(request, settings)
    response.set_cookie(settings.cookie_name, token, httponly=True, samesite="lax",
                        secure=secure, max_age=settings.jwt_ttl_minutes * 60, path="/")
    from app.services.messages import store as msg_store
    msg_store.add("info", "user", f"密码已修改：{user.username}", "本人在线自助修改", {})
    return {"ok": True}


class PasswordVerify(BaseModel):
    password: str = Field(min_length=1, max_length=128)


@router.post("/verify")
def verify_own_password(
    body: PasswordVerify,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """只校验密码对不对，不签发新 token —— 用于锁屏解锁。

    它同样是"猜密码"的入口，所以和登录共用失败计数/锁定。
    """
    key = _attempt_key(user.username, request.client.host if request.client else None)
    left = _locked_seconds(db, key)
    if left:
        raise Unauthorized(f"尝试次数过多，请 {left // 60 + 1} 分钟后再试")
    if not verify_password(body.password, user.password_hash):
        _record_fail(db, key)
        raise Unauthorized("密码不正确")
    _clear_fail(db, key)
    return {"ok": True}


# ---------------- 双因子（TOTP） ----------------

@router.post("/totp/start", dependencies=[Depends(require_csrf)])
def totp_start(
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
) -> dict:
    """生成密钥并返回 otpauth:// 链接（还没启用，等输对一次码）。"""
    secret = totp_secret()
    me.totp_secret = secret
    db.commit()
    return {"secret": secret, "uri": totp_uri(secret, me.username),
            "enabled": bool(me.totp_enabled)}


class TotpIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)


@router.post("/totp/enable", dependencies=[Depends(require_csrf)])
def totp_enable(
    body: TotpIn, db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
) -> dict:
    if not me.totp_secret:
        raise BadRequest("请先生成密钥", code="NO_SECRET")
    if not totp_verify(me.totp_secret, body.code):
        raise BadRequest("动态码不正确，请确认手机时间准确", code="TOTP_INVALID")
    me.totp_enabled = True
    db.commit()
    audit(db=db, action="auth.totp_enable", target=me.username, user=me)
    return {"ok": True, "enabled": True}


class TotpOff(BaseModel):
    password: str = Field(min_length=1, max_length=128)


@router.post("/totp/disable", dependencies=[Depends(require_csrf)])
def totp_disable(
    body: TotpOff, db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
) -> dict:
    if not verify_password(body.password, me.password_hash):
        raise BadRequest("密码不正确", code="BAD_PASSWORD")
    me.totp_enabled = False
    me.totp_secret = None
    db.commit()
    audit(db=db, action="auth.totp_disable", target=me.username, user=me)
    return {"ok": True, "enabled": False}
