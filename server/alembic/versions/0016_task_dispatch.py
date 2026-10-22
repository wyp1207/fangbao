"""任务下发写链路字段

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    cols = _cols("task_run")
    if not cols:
        return
    for name, col in (
        ("dispatched_at", sa.Column("dispatched_at", sa.DateTime, nullable=True)),
        ("last_progress_at", sa.Column("last_progress_at", sa.DateTime, nullable=True)),
        ("paused_at", sa.Column("paused_at", sa.DateTime, nullable=True)),
        ("dispatch_error", sa.Column("dispatch_error", sa.String(300), nullable=True)),
        ("order_json", sa.Column("order_json", sa.Text, nullable=True)),
    ):
        if name not in cols:
            op.add_column("task_run", col)


def downgrade() -> None:
    pass
