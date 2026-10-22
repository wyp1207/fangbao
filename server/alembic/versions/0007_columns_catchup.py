"""补齐开发期用 ALTER 加过、但没进迁移的列

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-22

背景：在 sqlite 开发库里直接 ALTER 加过几个字段，忘了写进迁移；
本地 sqlite 一直没问题，直到 8.40 上全新 MySQL 才暴露
（Unknown column 'video_source.show_on_dashboard'）。
这条迁移把缺的列一次补齐，全部幂等。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _add(table: str, name: str, col: sa.Column) -> None:
    if name not in _cols(table):
        op.add_column(table, col)
        print(f"  + {table}.{name}")


def upgrade() -> None:
    _add("video_source", "show_on_dashboard",
         sa.Column("show_on_dashboard", sa.Boolean, server_default=sa.false()))

    _add("alarm_record", "escalated_at", sa.Column("escalated_at", sa.DateTime, nullable=True))

    _add("notify_channel", "tier",
         sa.Column("tier", sa.Integer, server_default="1"))


def downgrade() -> None:
    # 不删列：降级时保留数据更安全
    pass
