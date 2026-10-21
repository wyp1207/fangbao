"""init

Revision ID: 0001
Revises:
Create Date: 2026-10-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="operator"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_user_username", "user", ["username"], unique=True)

    op.create_table(
        "robot",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, server_default="JCROB-01"),
        sa.Column("ip", sa.String(64), nullable=False, server_default="192.168.1.100"),
        sa.Column("port", sa.Integer, nullable=False, server_default="3546"),
        sa.Column("ws_port", sa.Integer, nullable=False, server_default="3547"),
        sa.Column("mode", sa.String(16), nullable=False, server_default="mock"),
        sa.Column("token_cipher", sa.Text, nullable=True),
        sa.Column("version", sa.String(32), nullable=True),
        sa.Column("slam_type", sa.String(16), nullable=True),
        sa.Column("capabilities_json", sa.Text, nullable=True),
        sa.Column("config_view_json", sa.Text, nullable=True),
        sa.Column("angle_unit_override", sa.String(8), nullable=False, server_default="auto"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_seen", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "operation_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ts", sa.DateTime, server_default=sa.func.now()),
        sa.Column("user_id", sa.Integer, nullable=True),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("client_ip", sa.String(64), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target", sa.String(128), nullable=True),
        sa.Column("params_json", sa.Text, nullable=True),
        sa.Column("success", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("result_summary", sa.Text, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
    )
    op.create_index("ix_operation_log_ts", "operation_log", ["ts"])


def downgrade() -> None:
    op.drop_index("ix_operation_log_ts", table_name="operation_log")
    op.drop_table("operation_log")
    op.drop_table("robot")
    op.drop_index("ix_user_username", table_name="user")
    op.drop_table("user")
