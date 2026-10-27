"""下发幂等 + 状态机正交字段（迁移 0024）

Revision ID: 0024
Revises: 0023
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

COLS = [
    ("order_id", sa.String(64)),
    ("order_update_id", sa.Integer),
    ("dispatch_state", sa.String(16)),
    ("dispatch_attempt", sa.Integer),
    ("dispatch_lease_until", sa.DateTime),
    ("cancel_requested_at", sa.DateTime),
    ("last_seq", sa.Integer),
]


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("task_run"):
        return
    have = {c["name"] for c in insp.get_columns("task_run")}
    for name, typ in COLS:
        if name not in have:
            if name in ("order_update_id", "dispatch_attempt", "last_seq"):
                op.add_column("task_run", sa.Column(name, typ, server_default="0"))
            elif name == "dispatch_state":
                op.add_column("task_run", sa.Column(name, typ, server_default="pending"))
            else:
                op.add_column("task_run", sa.Column(name, typ))

    # 唯一索引：同一订单号只能有一行（历史数据 order_id 为 NULL，不冲突）
    insp = sa.inspect(op.get_bind())
    idx = {i["name"] for i in insp.get_indexes("task_run")}
    if "ix_task_run_order_id" not in idx:
        op.create_index("ix_task_run_order_id", "task_run", ["order_id"], unique=True)

    # 资源锁表（D 用；先建好，代码可以后接）
    if not insp.has_table("resource_lock"):
        op.create_table(
            "resource_lock",
            sa.Column("key", sa.String(64), primary_key=True),
            sa.Column("run_id", sa.Integer),
            sa.Column("robot_id", sa.Integer),
            sa.Column("acquired_at", sa.DateTime),
            sa.Column("expires_at", sa.DateTime),
            sa.Column("note", sa.String(120)),
        )


def downgrade() -> None:
    pass
