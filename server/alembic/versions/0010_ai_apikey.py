"""AI 结果接入 + 机器身份（API Key）

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def _has(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if not _has("api_client"):
        op.create_table(
            "api_client",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("key_hash", sa.String(64), nullable=False),
            sa.Column("prefix", sa.String(12), server_default=""),
            sa.Column("scopes", sa.String(200), server_default=""),
            sa.Column("enabled", sa.Boolean, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
            sa.Column("last_used_at", sa.DateTime, nullable=True),
        )
        op.create_index("ix_api_client_key_hash", "api_client", ["key_hash"])

    if not _has("ai_algorithm"):
        op.create_table(
            "ai_algorithm",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("code", sa.String(48), nullable=False),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("category", sa.String(24), server_default="device"),
            sa.Column("unit", sa.String(16), nullable=True),
            sa.Column("min_confidence", sa.Float, server_default="0.6"),
            sa.Column("enabled", sa.Boolean, server_default=sa.true()),
        )
        op.create_index("ix_ai_algorithm_code", "ai_algorithm", ["code"], unique=True)

    if not _has("ai_result"):
        op.create_table(
            "ai_result",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("algorithm", sa.String(48), nullable=False),
            sa.Column("camera_id", sa.Integer, nullable=True),
            sa.Column("point_id", sa.Integer, nullable=True),
            sa.Column("value", sa.Float, nullable=True),
            sa.Column("text", sa.String(200), nullable=True),
            sa.Column("confidence", sa.Float, server_default="0"),
            sa.Column("image_path", sa.String(200), nullable=True),
            sa.Column("boxes_json", sa.Text, nullable=True),
            sa.Column("ts", sa.DateTime, server_default=sa.func.now()),
            sa.Column("alarm_id", sa.Integer, nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )
        op.create_index("ix_ai_result_algorithm", "ai_result", ["algorithm"])
        op.create_index("ix_ai_result_camera_id", "ai_result", ["camera_id"])
        op.create_index("ix_ai_result_ts", "ai_result", ["ts"])


def downgrade() -> None:
    for name in ("ai_result", "ai_algorithm", "api_client"):
        if _has(name):
            op.drop_table(name)
