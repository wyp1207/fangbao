from __future__ import annotations

from datetime import datetime, time

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class RecordPlan(Base):
    """录制计划：哪一路、星期几、几点到几点录。

    `days` 存 7 位字符串（周一→周日，'1' 表示启用），比 bitmask 好排错。
    调度器每 30 秒对一次表：窗口内且没在录 → 开；窗口外且是计划开的 → 停。
    """

    __tablename__ = "record_plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(64))
    days: Mapped[str] = mapped_column(String(7), default="1111111")
    start_time: Mapped[str] = mapped_column(String(5), default="00:00")
    end_time: Mapped[str] = mapped_column(String(5), default="23:59")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    def in_window(self, now: datetime) -> bool:
        weekday = now.weekday()          # 0=周一
        if self.days[weekday:weekday + 1] != "1":
            return False
        cur = now.time()
        try:
            start = time.fromisoformat(self.start_time)
            end = time.fromisoformat(self.end_time)
        except ValueError:
            return False
        if start <= end:
            return start <= cur <= end
        # 跨零点，如 22:00 → 06:00
        return cur >= start or cur <= end
