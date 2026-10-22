"""双因子（TOTP）

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("user"):
        return
    cols = {c["name"] for c in insp.get_columns("user")}
    if "totp_secret" not in cols:
        op.add_column("user", sa.Column("totp_secret", sa.String(64), nullable=True))
    if "totp_enabled" not in cols:
        op.add_column("user", sa.Column("totp_enabled", sa.Boolean, server_default=sa.false()))


def downgrade() -> None:
    pass
