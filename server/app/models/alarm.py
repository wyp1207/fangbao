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

    # 处置流程：确认 → 处置 → 关闭；每一步都留人和时间，供追溯与统计
    handled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    handled_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    handle_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    escalated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 条件消失自动恢复（行业通行做法：active → resolved，而不是让人手动关）
    # 告警搁置（ISA-18.2）：维修/标定期间临时屏蔽，到期自动恢复，必须留原因
    shelved_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    shelve_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(8), nullable=True)   # P1..P4

    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(32), nullable=True)  # handled/misreport/ignored
    close_note: Mapped[str | None] = mapped_column(Text, nullable=True)

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
            "handled_at": self.handled_at.isoformat(timespec="seconds") if self.handled_at else None,
            "handled_by": self.handled_by,
            "handle_note": self.handle_note,
            "escalated_at": self.escalated_at.isoformat(timespec="seconds") if self.escalated_at else None,
            "closed_at": self.closed_at.isoformat(timespec="seconds") if self.closed_at else None,
            "closed_by": self.closed_by,
            "resolution": self.resolution,
            "close_note": self.close_note,
            "status": (
                "closed" if self.closed_at else
                "handled" if self.handled_at else
                "acked" if self.acked_at else "new"
            ),
            "robot_id": self.robot_id,
            "camera_id": self.camera_id,
        }
