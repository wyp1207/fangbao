"""任务执行记录表

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _has(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if not _has("task_run"):
        op.create_table(
            "task_run",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("template_id", sa.Integer, nullable=True),
            sa.Column("robot_id", sa.Integer, nullable=True),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("status", sa.String(16), server_default="planned"),
            sa.Column("started_at", sa.DateTime, nullable=True),
            sa.Column("finished_at", sa.DateTime, nullable=True),
            sa.Column("external_id", sa.String(64), nullable=True),
            sa.Column("note", sa.String(200), nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )
        op.create_index("ix_task_run_status", "task_run", ["status"])
        op.create_index("ix_task_run_external_id", "task_run", ["external_id"])
        op.create_index("ix_task_run_created_at", "task_run", ["created_at"])

    if not _has("task_run_step"):
        op.create_table(
            "task_run_step",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("run_id", sa.Integer, nullable=False),
            sa.Column("seq", sa.Integer, server_default="0"),
            sa.Column("point_id", sa.Integer, nullable=True),
            sa.Column("point_name", sa.String(64), nullable=True),
            sa.Column("action", sa.String(24), server_default="photo"),
            sa.Column("status", sa.String(16), server_default="pending"),
            sa.Column("started_at", sa.DateTime, nullable=True),
            sa.Column("finished_at", sa.DateTime, nullable=True),
            sa.Column("result_json", sa.Text, nullable=True),
            sa.Column("error", sa.String(200), nullable=True),
        )
        op.create_index("ix_task_run_step_run_id", "task_run_step", ["run_id"])


def downgrade() -> None:
    for name in ("task_run_step", "task_run"):
        if _has(name):
            op.drop_table(name)
