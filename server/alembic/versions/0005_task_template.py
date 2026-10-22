"""巡检任务模板 + 点位分组

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _has(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def _cols(table: str) -> set[str]:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(table):
        return set()
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    if not _has("task_template"):
        op.create_table(
            "task_template",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("map_id", sa.Integer, nullable=True),
            sa.Column("robot_id", sa.Integer, nullable=True),
            sa.Column("actions_json", sa.Text, nullable=True),  # MySQL 的 TEXT 不能带 DEFAULT
            sa.Column("loop", sa.Boolean, server_default=sa.false()),
            sa.Column("note", sa.String(200), nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )

    # 点位分组：老库补列，已有数据归到"默认分组"
    if "group_name" not in _cols("point_draft"):
        op.add_column(
            "point_draft",
            sa.Column("group_name", sa.String(32), server_default="默认分组"),
        )


def downgrade() -> None:
    if _has("task_template"):
        op.drop_table("task_template")
