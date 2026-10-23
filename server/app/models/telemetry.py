from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class TelemetrySample(Base):
    """运行数据采样。

    为什么单独建表而不是从告警/消息里推：领导要看"过去 24 小时电量怎么掉的、
    跑了多远、速度峰值多少"，这些只能靠连续采样。

    采样频率 10 秒（可在设置里调），保留 7 天，超期由清理线程删除。
    """

    __tablename__ = "telemetry_sample"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    robot_id: Mapped[int] = mapped_column(Integer, index=True, default=1)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)

    battery: Mapped[float | None] = mapped_column(Float, nullable=True)
    voltage: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    yaw_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    x: Mapped[float | None] = mapped_column(Float, nullable=True)
    y: Mapped[float | None] = mapped_column(Float, nullable=True)
    theta: Mapped[float | None] = mapped_column(Float, nullable=True)

    online: Mapped[bool] = mapped_column(Boolean, default=False)
    estop: Mapped[bool] = mapped_column(Boolean, default=False)


class TelemetryRollup(Base):
    """分钟级聚合：原始 10s 数据保留 7 天，聚合保留 180 天。

    为什么这样做：MySQL 存 10s 原始数据，一年 6300 万行，
    报表按 180 天查会扫全表；先聚合再查，量级降到 1/60。
    """

    __tablename__ = "telemetry_rollup"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bucket: Mapped[datetime] = mapped_column(DateTime, index=True)
    robot_id: Mapped[int | None] = mapped_column(Integer, index=True)
    samples: Mapped[int] = mapped_column(Integer, default=0)
    battery_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    battery_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    online_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
