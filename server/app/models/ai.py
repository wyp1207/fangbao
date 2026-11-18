from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
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
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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

    幂等键 (source_id, external_event_id) 唯一：盒子重推/轮询重叠不会产生两条。
    """

    __tablename__ = "ai_result"
    __table_args__ = (
        UniqueConstraint("source_id", "external_event_id", name="uq_ai_result_event"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    external_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    algorithm: Mapped[str] = mapped_column(String(48), index=True)
    camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    point_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stream_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    pan: Mapped[float | None] = mapped_column(Float, nullable=True)
    tilt: Mapped[float | None] = mapped_column(Float, nullable=True)
    zoom: Mapped[float | None] = mapped_column(Float, nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    image_path: Mapped[str | None] = mapped_column(String(200), nullable=True)
    boxes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 盒子原始记录 + 图片 URL（Phase 4 先不下载原图，保留可回补的线索）
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 真实回调（.170 webhook）的盒子侧标识：平台相机/算法台账还没做映射，
    # 先把盒子原值存下来，后面建告警、按盒子字段对账时不用再猜
    external_camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_camera_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_algorithm_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    review_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    diagnosis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_clip: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    alarm_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AiSource(Base):
    """边缘 AI 盒子（CRIP/其他）注册。密钥只存引用名，真实值在 env。"""

    __tablename__ = "ai_source"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    base_url: Mapped[str] = mapped_column(String(255))
    vendor: Mapped[str] = mapped_column(String(32), default="crip")
    auth_type: Mapped[str] = mapped_column(String(16), default="openapi")
    auth_ref: Mapped[str] = mapped_column(String(64), default="")
    poll_interval_s: Mapped[int] = mapped_column(Integer, default=5)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AiStream(Base):
    """机器人身上的视频流：可见光/热成像/前置，主/子码流。"""

    __tablename__ = "ai_stream"
    __table_args__ = (
        UniqueConstraint("robot_id", "stream_type", "role", name="uq_ai_stream_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    robot_id: Mapped[int] = mapped_column(Integer, index=True)
    stream_type: Mapped[str] = mapped_column(String(16))   # visible/thermal/front
    role: Mapped[str] = mapped_column(String(8), default="main")  # main/sub
    rtsp_url: Mapped[str] = mapped_column(String(512), default="")
    channel: Mapped[str | None] = mapped_column(String(8), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    codec: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/placeholder/disabled
    note: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AiPresetRule(Base):
    """云台预置位 ↔ 算法/ROI/停留时间。预置位只用 1–32。"""

    __tablename__ = "ai_preset_rule"
    __table_args__ = (
        UniqueConstraint("stream_id", "preset_id", name="uq_ai_preset_rule"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stream_id: Mapped[int] = mapped_column(Integer, index=True)
    preset_id: Mapped[int] = mapped_column(Integer)
    preset_name: Mapped[str] = mapped_column(String(32), default="")
    pan: Mapped[float | None] = mapped_column(Float, nullable=True)
    tilt: Mapped[float | None] = mapped_column(Float, nullable=True)
    zoom: Mapped[float | None] = mapped_column(Float, nullable=True)
    tolerance_deg: Mapped[float] = mapped_column(Float, default=2.0)
    dwell_s: Mapped[int] = mapped_column(Integer, default=20)
    roi_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    algorithm_ids: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AiReview(Base):
    """人工/模型复核记录。"""

    __tablename__ = "ai_review"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_id: Mapped[int] = mapped_column(Integer, index=True)
    reviewer: Mapped[str] = mapped_column(String(64), default="")
    state: Mapped[str] = mapped_column(String(16), default="confirmed")  # confirmed/rejected/uncertain
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AiSampleLabel(Base):
    """误报/漏报标注，用于后续调阈值/重训。"""

    __tablename__ = "ai_sample_label"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    label: Mapped[str] = mapped_column(String(8))  # tp/fp/fn
    reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    labeled_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
