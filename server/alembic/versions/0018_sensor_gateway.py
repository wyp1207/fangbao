"""环境采集网关

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if insp.has_table("sensor_gateway"):
        return
    op.create_table(
        "sensor_gateway",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("protocol", sa.String(16), server_default="modbus"),
        sa.Column("host", sa.String(64), nullable=False),
        sa.Column("port", sa.Integer, server_default="502"),
        sa.Column("unit_id", sa.Integer, server_default="1"),
        sa.Column("topic", sa.String(128), nullable=True),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("password", sa.String(64), nullable=True),
        sa.Column("mapping_json", sa.Text, nullable=True),
        sa.Column("interval_s", sa.Integer, server_default="10"),
        sa.Column("enabled", sa.Boolean, server_default=sa.true()),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    pass
