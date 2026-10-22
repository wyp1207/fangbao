from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class PlatformMap(Base):
    """平台侧地图库。

    为什么要单独存：机器人只认自己 SLAM 建出来的图；换场地时客户给的图纸、
    或者想给领导看一张"干净的场地图"，都得先进平台，再由人标定比例尺与原点。
    `robot_map_name` 是两者的桥：留空表示"只是平台底图，未与机器人对应"。
    """

    __tablename__ = "platform_map"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    floor: Mapped[str] = mapped_column(String(32), default="1F")
    station: Mapped[str] = mapped_column(String(64), default="默认场站")
    resolution: Mapped[float] = mapped_column(Float, default=0.05)   # 米/像素
    origin_x: Mapped[float] = mapped_column(Float, default=0.0)
    origin_y: Mapped[float] = mapped_column(Float, default=0.0)
    origin_theta: Mapped[float] = mapped_column(Float, default=0.0)
    image_path: Mapped[str] = mapped_column(String(255))
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    robot_map_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class PointDraft(Base):
    """平台侧点位草稿。

    现状：机器人上的点位只能读，不能写（写操作等现场授权）。
    所以平台上"新增点位"先存草稿，标 synced=False，等授权后再下发。
    这不是假数据：草稿是用户自己点的坐标，真实存在，只是还没同步给机器人。
    """

    __tablename__ = "point_draft"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    map_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(64))
    group_name: Mapped[str] = mapped_column(String(32), default="默认分组")
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    theta: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    synced: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
