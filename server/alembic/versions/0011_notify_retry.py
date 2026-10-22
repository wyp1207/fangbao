"""通知失败重试字段

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    cols = _cols("notify_log")
    if not cols:
        return
    if "payload_json" not in cols:
        op.add_column("notify_log", sa.Column("payload_json", sa.Text, nullable=True))
    if "attempts" not in cols:
        op.add_column("notify_log", sa.Column("attempts", sa.Integer, server_default="1"))
    if "next_retry_at" not in cols:
        op.add_column("notify_log", sa.Column("next_retry_at", sa.DateTime, nullable=True))
        op.create_index("ix_notify_log_next_retry_at", "notify_log", ["next_retry_at"])


def downgrade() -> None:
    pass
