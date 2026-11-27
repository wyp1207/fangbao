from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Site(Base):
    """场站（site）：一台设备、一张地图、一个模板都归属某个场站。

    为什么现在加：之前只有 `station` 这个自由文本，写法一抖（"实验室"/"实验室 "
    /"实 验 室"）就被当成两个地方，设备/地图/任务之间没有任何硬边界。
    site 把"同一现场"变成可校验的外键（逻辑外键，不建物理 FK——
    MySQL 与 SQLite 行为不一致，历史库又有脏数据，物理 FK 会在迁移时炸）。

    status: 1 启用，0 停用（不删数据，停用即可）。
    """

    __tablename__ = "site"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # code 给程序用：唯一、稳定、可写进 URL/日志，不随中文名改动
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    address: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, server_default=func.now()
    )
