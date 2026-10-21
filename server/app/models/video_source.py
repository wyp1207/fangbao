from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class VideoSource(Base):
    """视频源（摄像头）。

    url 里带 RTSP 账号密码，属于敏感字段：
    - 只存在服务端，接口返回时一律打码成 rtsp://user:***@host；
    - 前端编辑时如果没改密码，提交回来的是打码串，服务端要还原成原值。
    """

    __tablename__ = "video_source"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))                  # 显示名，如「充电房-可见光」
    group_name: Mapped[str] = mapped_column(String(32), default="默认分组")
    vendor: Mapped[str] = mapped_column(String(16), default="other")  # hikvision/dahua/other
    url: Mapped[str] = mapped_column(String(512))
    # go2rtc 里的流名；配了就能走 go2rtc 的 MSE/WebRTC 播放（低延迟），空则退回 MJPEG
    stream_name: Mapped[str] = mapped_column(String(32), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
