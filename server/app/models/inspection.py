from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class InspectionPlan(Base):
    """人工巡检计划：班次 + 要查的点位 + 检查项 + 责任人。

    为什么单独建：PPT 里"人工巡检数字化"要的是"计划派发→扫码打点→现场记录→缺陷上报"，
    核心是把纸质巡检变成可追溯的结构化数据。计划是模板，任务是一次执行。
    """

    __tablename__ = "inspection_plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    station: Mapped[str] = mapped_column(String(64), default="默认场站")
    shift: Mapped[str] = mapped_column(String(16), default="早班")   # 早班/中班/夜班
    assignee_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # [{point_id, name, code, checks: ["外观","温度","渗漏"]}]
    items_json: Mapped[str] = mapped_column(Text, default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class InspectionTask(Base):
    """一次人工巡检任务（可由计划生成）。"""

    __tablename__ = "inspection_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(64))
    assignee_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class InspectionItem(Base):
    """任务里的一个打点项：扫码到位 + 勾检查项 + 拍照 + 结论。"""

    __tablename__ = "inspection_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(Integer, index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    point_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    point_name: Mapped[str] = mapped_column(String(64))
    code: Mapped[str | None] = mapped_column(String(32), nullable=True)   # 二维码/NFC 里写的编号
    checks_json: Mapped[str] = mapped_column(Text, default="[]")          # 检查项列表
    result: Mapped[str] = mapped_column(String(16), default="pending")     # pending/ok/abnormal/skipped
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    photos_json: Mapped[str] = mapped_column(Text, default="[]")
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WorkOrder(Base):
    """工单：告警转单或人工缺陷上报，派单到人、处置回填、复核销号。

    PPT 的"告警工单闭环"七步：识别→定级→推送→派单→处置→复核→归档。
    我们这里 status 覆盖后五步，escalated_at 记录超时升级。
    """

    __tablename__ = "work_order"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(16), default="manual")   # alarm/manual/ai
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    level: Mapped[str] = mapped_column(String(16), default="warn")       # critical/warn/info
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    assignee_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    photos_json: Mapped[str] = mapped_column(Text, default="[]")
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
