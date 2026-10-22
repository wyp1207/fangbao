from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class TaskRun(Base):
    """一次巡检任务的执行记录。

    为什么现在就要建：真机到场后第一件事就是"下发—执行—回传结果"，
    如果没有这张表，机器人跑完的结果无处可存，只能看日志。
    现在先建好表 + 接收接口，真机接上就能灌数据。

    status:
      planned   平台侧计划（还没下发，因为写操作未开放）
      running   机器人已开始执行
      done      正常结束
      failed    失败（含中途取消）
      cancelled 人工取消

    external_id：机器人那边的任务 id，用来做幂等（重复上报不会产生两条）。
    """

    __tablename__ = "task_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    robot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="planned", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    # 写链路（下发/暂停/看门狗）
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_progress_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dispatch_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    order_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class TaskRunStep(Base):
    """任务里每个点位的执行结果。"""

    __tablename__ = "task_run_step"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    point_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    point_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(24), default="photo")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/ok/failed/skipped
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
