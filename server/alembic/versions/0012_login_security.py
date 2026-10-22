"""登录安全：锁定落库、密码历史、密码有效期

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _has(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    cols = _cols("user")
    if cols:
        if "failed_logins" not in cols:
            op.add_column("user", sa.Column("failed_logins", sa.Integer, server_default="0"))
        if "locked_until" not in cols:
            op.add_column("user", sa.Column("locked_until", sa.DateTime, nullable=True))
        if "password_changed_at" not in cols:
            op.add_column("user", sa.Column("password_changed_at", sa.DateTime, nullable=True))

    if not _has("password_history"):
        op.create_table(
            "password_history",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("user_id", sa.Integer, nullable=False),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )
        op.create_index("ix_password_history_user_id", "password_history", ["user_id"])

    if not _has("login_attempt"):
        op.create_table(
            "login_attempt",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("key", sa.String(160), nullable=False),
            sa.Column("fails", sa.Integer, server_default="0"),
            sa.Column("locked_until", sa.DateTime, nullable=True),
            sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        )
        op.create_index("ix_login_attempt_key", "login_attempt", ["key"], unique=True)


def downgrade() -> None:
    pass
