from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AlarmRecord(Base):
    """告警（持久化）。

    和内存版 AlarmStore 的区别：这里是**真相源**，重启不丢、可按时间/级别/指标查。
    camera_id 在告警产生时固化：值为 null 表示"当时没有关联摄像头"，
    而不是"以后再去猜"——没有关联就不给回放入口，避免误导。
    """

    __tablename__ = "alarm_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric: Mapped[str] = mapped_column(String(32), index=True)
    level: Mapped[str] = mapped_column(String(16), index=True)  # warn | critical
    message: Mapped[str] = mapped_column(String(255))
    value_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    robot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_alarm_time_level", "started_at", "level"),)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "metric": self.metric,
            "level": self.level,
            "message": self.message,
            "value": self.value_json,
            "started_at": self.started_at.isoformat(timespec="seconds") if self.started_at else None,
            "acked_at": self.acked_at.isoformat(timespec="seconds") if self.acked_at else None,
            "acked_by": self.acked_by,
            "robot_id": self.robot_id,
            "camera_id": self.camera_id,
        }
