from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
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

    # ---- 下发幂等（迁移 0024）；主状态仍是上面那 5 个，不扩枚举 ----
    order_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    order_update_id: Mapped[int] = mapped_column(Integer, default=0)
    dispatch_state: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    dispatch_attempt: Mapped[int] = mapped_column(Integer, default=0)
    dispatch_lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seq: Mapped[int] = mapped_column(Integer, default=0)


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


class TaskEvent(Base):
    """任务执行事件（时间线，只追加）。

    为什么单独一张表：`task_run.status` 只有一个"当前值"，"什么时候下发的、
    中途暂停过几次、哪一步重试了、最后是超时还是车端报失败"全都看不到，
    只能翻服务日志。参考 Open-RMF 的 task state 变化、Nav2 行为树节点事件、
    Temporal 的 activity history：把每次状态迁移按 (run_id, seq) 追加下来，
    前端详情里就是一条能复盘的时间线。

    kind 是稳定的英文字面量（前端翻中文），新类型只追加、不改旧值。
    seq 按 run 从 1 递增；事件失败不能影响主流程（调用方用 safe_log）。
    """

    __tablename__ = "task_event"
    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_task_event_run_seq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(Integer)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(24))
    message: Mapped[str] = mapped_column(String(255), default="")
    data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
