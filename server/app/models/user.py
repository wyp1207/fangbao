from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="operator")  # admin/operator/viewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 初次登录/管理员重置后为 True：前端强制改密，后端也拦住写操作
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    # 登录防爆破落库：进程重启后锁定依然有效（原来只在内存里）
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # 防重放：记最后用过的计数器（同一 30s 窗内的码不能再用一次）
    totp_last_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 会话版本：登出/改密/停用时 +1，旧 JWT 立即失效（JWT 本身无状态）
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PasswordHistory(Base):
    """最近用过的密码哈希：改密时禁止复用最近 5 次（等保要求）。"""

    __tablename__ = "password_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class LoginAttempt(Base):
    """按 账号|IP 计的失败次数。不存在的账号也要能锁（防用户名枚举爆破）。"""

    __tablename__ = "login_attempt"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    fails: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
