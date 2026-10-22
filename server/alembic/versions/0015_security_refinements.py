"""安全细化：TOTP 防重放、API Key 过期、告警自动恢复

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if "totp_last_step" not in _cols("user") and _cols("user"):
        op.add_column("user", sa.Column("totp_last_step", sa.Integer, nullable=True))
    if "expires_at" not in _cols("api_client") and _cols("api_client"):
        op.add_column("api_client", sa.Column("expires_at", sa.DateTime, nullable=True))
    if "token_version" not in _cols("user") and _cols("user"):
        op.add_column("user", sa.Column("token_version", sa.Integer, server_default="1"))
    if "resolved_at" not in _cols("alarm_record") and _cols("alarm_record"):
        op.add_column("alarm_record", sa.Column("resolved_at", sa.DateTime, nullable=True))


def downgrade() -> None:
    pass
