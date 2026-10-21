"""补 video_source 表（幂等）

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-21

背景：基线 0001 漏了 video_source（当时靠 dev 的 create_all 建表），
0002 里补上了。但已经跑过 0002 的环境不会再执行一次，
所以再加一条幂等迁移，确保所有环境最终都有这张表。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("video_source"):
        return
    op.create_table(
        "video_source",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("group_name", sa.String(32), server_default="默认分组"),
        sa.Column("vendor", sa.String(16), server_default="other"),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("stream_name", sa.String(32), server_default=""),
        sa.Column("enabled", sa.Boolean, server_default=sa.true()),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    # 不删：0003 只是补漏，回滚到 0002 时保留这张表更安全
    pass
