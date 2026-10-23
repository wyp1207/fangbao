from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Sensor(Base):
    """环境传感器台账。

    阈值默认是 NULL，不是 0：没标定就不报警，页面显示「未标定」。
    标定值由现场按仪表/检定证书填，填了才参与告警判定。
    """

    __tablename__ = "sensor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(24), index=True)   # gas/temperature/humidity/pm/noise/smoke
    unit: Mapped[str] = mapped_column(String(16), default="")
    station: Mapped[str] = mapped_column(String(64), default="默认场站")
    location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    serial: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 阈值（None = 未标定）
    warn_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    warn_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    crit_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    crit_high: Mapped[float | None] = mapped_column(Float, nullable=True)

    robot_id: Mapped[int | None] = mapped_column(Integer, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class SensorReading(Base):
    """读数。灌数来源：真机环境模块 / 外部采集器 / 手填。"""

    __tablename__ = "sensor_reading"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sensor_id: Mapped[int] = mapped_column(Integer, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    value: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(24), default="manual")  # manual/robot/gateway
