from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class NotifyChannel(Base):
    """告警通知通道。

    config_json 按类型不同：
      wecom / dingtalk : {"url": "https://..."}
      generic          : {"url": "https://...", "headers": {...}}
      email            : {"host","port","user","password","to":[...],"tls":true}
    敏感字段（URL 里的 key、邮箱密码）存在 config_json 里，
    接口返回时统一打码，编辑时留空表示不改。
    """

    __tablename__ = "notify_channel"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(24))          # wecom/dingtalk/generic/email
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    min_level: Mapped[str] = mapped_column(String(16), default="critical")  # warn|critical
    # 同一通道对同一指标的静默期（分钟），防止刷屏
    min_interval_min: Mapped[int] = mapped_column(Integer, default=10)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class NotifyLog(Base):
    """投递记录：谁发给谁、成不成、失败原因。"""

    __tablename__ = "notify_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    channel_id: Mapped[int] = mapped_column(Integer, index=True)
    channel_name: Mapped[str] = mapped_column(String(64), default="")
    alarm_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
