from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Robot(Base):
    __tablename__ = "robot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), default="JCROB-01")
    ip: Mapped[str] = mapped_column(String(64), default="192.168.1.100")
    port: Mapped[int] = mapped_column(Integer, default=3546)
    ws_port: Mapped[int] = mapped_column(Integer, default=3547)
    mode: Mapped[str] = mapped_column(String(16), default="mock")  # mock | http

    # ---- 多设备接入 ----
    # device_type：本体型号（决定用哪个适配器）；adapter：实际协议实现
    device_type: Mapped[str] = mapped_column(String(32), default="jcrob_wheel")
    adapter: Mapped[str] = mapped_column(String(32), default="jcrob_http")
    station: Mapped[str] = mapped_column(String(64), default="默认场站")
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    password_cipher: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # 机器人 token：对称加密后落库，密钥在环境变量里；平台仍要拿原文调接口，
    # 所以它是“降低泄露面”，不是“不可破解”。真正的防线是脱敏与网络隔离。
    token_cipher: Mapped[str | None] = mapped_column(Text, nullable=True)

    version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slam_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    capabilities_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_view_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 角度单位覆盖：auto | deg | rad，实测后写死
    angle_unit_override: Mapped[str] = mapped_column(String(8), default="auto")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
