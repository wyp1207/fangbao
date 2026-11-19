"""迁移 0029：任务执行事件时间线（task_event）。

为什么加这张表：`task_run.status` 只有一个当前值，"什么时候下发、暂停过几次、
哪一步重试过、最后是超时还是车端报失败" 都留不下来，只能翻服务日志。
事件表按 (run_id, seq) 追加每次状态迁移，前端详情里就是一条时间线。
参考 Open-RMF 的 task state 变化 / Nav2 行为树事件 / Temporal activity history，
纯本表实现，无外部依赖。

幂等：表/索引已存在就跳过（开发库可能已由 create_all 建过）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("task_event"):
        op.create_table(
            "task_event",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("run_id", sa.Integer, nullable=False),
            sa.Column("seq", sa.Integer, nullable=False, server_default="0"),
            sa.Column("kind", sa.String(24), nullable=False),
            sa.Column("message", sa.String(255), server_default=""),
            sa.Column("data_json", sa.Text),
            sa.Column("actor", sa.String(64), server_default="system"),
            sa.Column("created_at", sa.DateTime),
        )
        insp = sa.inspect(op.get_bind())

    # 索引单独补：唯一/普通索引名与 ORM 的默认名保持一致，避免重复建
    idx = {i["name"] for i in insp.get_indexes("task_event")}
    if "ix_task_event_run_id" not in idx:
        op.create_index("ix_task_event_run_id", "task_event", ["run_id"])
    if "ix_task_event_created_at" not in idx:
        op.create_index("ix_task_event_created_at", "task_event", ["created_at"])


def downgrade() -> None:
    # 事件是审计历史：降级不删表，避免丢已发生的事实
    pass
