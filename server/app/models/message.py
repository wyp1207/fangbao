from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class MessageRecord(Base):
    """消息中心（持久化）：系统事件留痕，重启不丢。"""

    __tablename__ = "message_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    level: Mapped[str] = mapped_column(String(16), default="info")   # info | warn | danger
    source: Mapped[str] = mapped_column(String(16), index=True)      # system/video/user/alarm
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    link_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ts": self.ts.timestamp() if self.ts else 0,
            "level": self.level,
            "source": self.source,
            "title": self.title,
            "body": self.body or "",
        }
