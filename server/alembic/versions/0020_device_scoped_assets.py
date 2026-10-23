"""设备维度绑定：sensor/video_source 增加 robot_id，robot 增加 capabilities

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())

    def has_col(table: str, col: str) -> bool:
        return insp.has_table(table) and col in {c["name"] for c in insp.get_columns(table)}

    if not has_col("sensor", "robot_id"):
        op.add_column("sensor", sa.Column("robot_id", sa.Integer, index=True))
    if not has_col("video_source", "robot_id"):
        op.add_column("video_source", sa.Column("robot_id", sa.Integer, index=True))
    if not has_col("robot", "capabilities_json"):
        op.add_column("robot", sa.Column("capabilities_json", sa.Text))


def downgrade() -> None:
    pass
