"""点位到点半径

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("point_draft"):
        return
    cols = {c["name"] for c in insp.get_columns("point_draft")}
    if "arrive_radius_m" not in cols:
        op.add_column("point_draft", sa.Column("arrive_radius_m", sa.Float, server_default="1.0"))


def downgrade() -> None:
    pass
