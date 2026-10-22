from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ApiClient(Base):
    """机器身份（机器人、算法盒、厂内系统对接用）。

    为什么不能复用用户账号：这些调用方拿不到浏览器 Cookie/CSRF，
    也没有"人"来改密码；必须有自己的凭据 + 权限范围 + 可吊销。
    key 只存哈希，明文只在创建时返回一次。
    """

    __tablename__ = "api_client"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    key_hash: Mapped[str] = mapped_column(String(64), index=True)   # sha256 hex
    prefix: Mapped[str] = mapped_column(String(12), default="")     # 展示用前 8 位
    scopes: Mapped[str] = mapped_column(String(200), default="")    # 逗号分隔
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_key() -> tuple[str, str, str]:
    """返回 (明文, 哈希, 前缀)。明文形如 jck_xxx，只在创建时给一次。"""
    raw = "jck_" + secrets.token_urlsafe(32)
    return raw, hash_key(raw), raw[:12]


class AiAlgorithm(Base):
    """算法注册表：哪些算法、叫什么、什么时候该报警。"""

    __tablename__ = "ai_algorithm"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(48), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(24), default="device")  # device/env/person/safety
    unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    min_confidence: Mapped[float] = mapped_column(Float, default=0.6)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AiResult(Base):
    """一条算法识别结果。原图落盘，库里只存路径。

    幂等键 (camera_id, algorithm, ts) 唯一：算法服务重试/重复推送不会产生两条结果。
    """

    __tablename__ = "ai_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    algorithm: Mapped[str] = mapped_column(String(48), index=True)
    camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    point_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    image_path: Mapped[str | None] = mapped_column(String(200), nullable=True)
    boxes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    alarm_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
