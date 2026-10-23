"""遥测降采样表 + 索引（为将来换时序库留口子）

Revision ID: 0023
Revises: 0022
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("telemetry_rollup"):
        op.create_table(
            "telemetry_rollup",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("bucket", sa.DateTime, index=True),   # 分钟对齐
            sa.Column("robot_id", sa.Integer, index=True),
            sa.Column("samples", sa.Integer),
            sa.Column("battery_avg", sa.Float),
            sa.Column("battery_min", sa.Float),
            sa.Column("speed_avg", sa.Float),
            sa.Column("online_ratio", sa.Float),
        )

    if insp.has_table("telemetry_sample"):
        have = {i["name"] for i in insp.get_indexes("telemetry_sample")}
        if "ix_telemetry_ts_robot" not in have:
            op.create_index("ix_telemetry_ts_robot", "telemetry_sample", ["ts", "robot_id"])


def downgrade() -> None:
    pass
