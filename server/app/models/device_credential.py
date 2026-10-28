"""设备接入凭证表（迁移 0025）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class DeviceCredential(Base):
    __tablename__ = "device_credential"
    __table_args__ = (UniqueConstraint("robot_id", name="uq_device_credential_robot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    robot_id: Mapped[int] = mapped_column(Integer, index=True)
    key_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    secret_enc: Mapped[str] = mapped_column(String(256))
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DeviceNonce(Base):
    __tablename__ = "device_nonce"
    __table_args__ = (UniqueConstraint("key_id", "nonce", name="uq_device_nonce"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key_id: Mapped[str] = mapped_column(String(64), index=True)
    nonce: Mapped[str] = mapped_column(String(64))
    ts: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
