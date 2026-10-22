"""审计哈希链

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("operation_log"):
        return
    cols = {c["name"] for c in insp.get_columns("operation_log")}
    if "prev_hash" not in cols:
        op.add_column("operation_log", sa.Column("prev_hash", sa.String(64), nullable=True))
    if "row_hash" not in cols:
        op.add_column("operation_log", sa.Column("row_hash", sa.String(64), nullable=True))
        op.create_index("ix_operation_log_row_hash", "operation_log", ["row_hash"])


def downgrade() -> None:
    pass
