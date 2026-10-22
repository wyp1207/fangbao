"""人工巡检数字化 + 工单闭环

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-22

对应客户方案 PPT 模块三（人工数字化）与模块五（告警工单闭环）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _has(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if not _has("inspection_plan"):
        op.create_table(
            "inspection_plan",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("station", sa.String(64), server_default="默认场站"),
            sa.Column("shift", sa.String(16), server_default="早班"),
            sa.Column("assignee_id", sa.Integer, nullable=True),
            sa.Column("items_json", sa.Text, nullable=True),   # MySQL 的 TEXT 不能带 DEFAULT
            sa.Column("enabled", sa.Boolean, server_default=sa.true()),
            sa.Column("note", sa.String(200), nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )

    if not _has("inspection_task"):
        op.create_table(
            "inspection_task",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("plan_id", sa.Integer, nullable=True),
            sa.Column("title", sa.String(64), nullable=False),
            sa.Column("assignee_id", sa.Integer, nullable=True),
            sa.Column("due_at", sa.DateTime, nullable=True),
            sa.Column("status", sa.String(16), server_default="pending"),
            sa.Column("started_at", sa.DateTime, nullable=True),
            sa.Column("finished_at", sa.DateTime, nullable=True),
            sa.Column("note", sa.String(200), nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )
        op.create_index("ix_inspection_task_status", "inspection_task", ["status"])
        op.create_index("ix_inspection_task_created_at", "inspection_task", ["created_at"])

    if not _has("inspection_item"):
        op.create_table(
            "inspection_item",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("task_id", sa.Integer, nullable=False),
            sa.Column("seq", sa.Integer, server_default="0"),
            sa.Column("point_id", sa.Integer, nullable=True),
            sa.Column("point_name", sa.String(64), nullable=False),
            sa.Column("code", sa.String(32), nullable=True),
            sa.Column("checks_json", sa.Text, nullable=True),
            sa.Column("result", sa.String(16), server_default="pending"),
            sa.Column("note", sa.String(200), nullable=True),
            sa.Column("photos_json", sa.Text, nullable=True),
            sa.Column("scanned_at", sa.DateTime, nullable=True),
            sa.Column("checked_at", sa.DateTime, nullable=True),
        )
        op.create_index("ix_inspection_item_task_id", "inspection_item", ["task_id"])

    if not _has("work_order"):
        op.create_table(
            "work_order",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("code", sa.String(32), nullable=True),
            sa.Column("title", sa.String(120), nullable=False),
            sa.Column("source", sa.String(16), server_default="manual"),
            sa.Column("source_id", sa.Integer, nullable=True),
            sa.Column("level", sa.String(16), server_default="warn"),
            sa.Column("status", sa.String(16), server_default="open"),
            sa.Column("assignee_id", sa.Integer, nullable=True),
            sa.Column("due_at", sa.DateTime, nullable=True),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("photos_json", sa.Text, nullable=True),
            sa.Column("resolution", sa.Text, nullable=True),
            sa.Column("escalated_at", sa.DateTime, nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
            sa.Column("closed_at", sa.DateTime, nullable=True),
        )
        op.create_index("ix_work_order_status", "work_order", ["status"])
        op.create_index("ix_work_order_code", "work_order", ["code"])
        op.create_index("ix_work_order_created_at", "work_order", ["created_at"])


def downgrade() -> None:
    for name in ("work_order", "inspection_item", "inspection_task", "inspection_plan"):
        if _has(name):
            op.drop_table(name)
