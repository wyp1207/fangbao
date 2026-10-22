from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class TaskTemplate(Base):
    """巡检任务模板（平台侧草稿）。

    现在不能下发——机器人写操作要等真机联调 + 现场授权。
    模板的价值是：现场先按点位把"走哪几个点、每个点做什么"配好，
    真机到了直接对着模板下发，不用在客户面前现配。

    动作序列存 JSON：
      [{"point_id": 1, "action": "photo", "params": {"dur": 3}},
       {"point_id": 2, "action": "wait",  "params": {"sec": 5}}]
    action 只能是我们和机器人协议里确认过的类型（见 ACTIONS）。
    """

    __tablename__ = "task_template"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    map_id: Mapped[int | None] = mapped_column(Integer, nullable=True)       # 平台地图库 id
    robot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actions_json: Mapped[str] = mapped_column(Text, default="[]")
    loop: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
