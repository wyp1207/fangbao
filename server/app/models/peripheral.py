"""外设实例：现场"真挂上去"的硬件（云台、热像仪、气体/噪声/粉尘传感器…）。

为什么要这张表：同一个场站里每台设备的外设可能完全不同，
页面必须按"这台设备实际有什么"渲染，而不是按型号写死。
传感器/视频源继续保留原表（读数、流地址），这里只做"归属与类型"的登记。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Peripheral(Base):
    __tablename__ = "peripheral"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    robot_id: Mapped[int | None] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)   # camera/thermal/ptz/gas/env/noise/dust/speaker
    vendor: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(32), nullable=True)  # CH101 / /dev/ttyUSB0 / 0x2000
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    sensor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
