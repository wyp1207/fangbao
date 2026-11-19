"""迁移 0030：task_event 加 (run_id, seq) 唯一约束，去掉冗余单列索引。

并发写者（下发轮询/巡航/HTTP/对账）可能同时算出同一个 seq；
唯一约束把“撞号”变成可重试的 IntegrityError，而不是静默写出两条。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("task_event"):
        return

    # 先查重复；有重复就不能加唯一约束，明确报错让人工处理
    dup = op.get_bind().execute(sa.text(
        "select run_id, seq, count(*) c from task_event "
        "group by run_id, seq having count(*) > 1"
    )).fetchall()
    if dup:
        raise RuntimeError(f"task_event 存在重复 (run_id, seq)：{dup[:10]}，请先人工去重")

    idx = {i["name"] for i in insp.get_indexes("task_event")}
    if "uq_task_event_run_seq" not in idx:
        op.create_index(
            "uq_task_event_run_seq", "task_event", ["run_id", "seq"], unique=True
        )
    if "ix_task_event_run_id" in idx:
        op.drop_index("ix_task_event_run_id", table_name="task_event")


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("task_event"):
        return
    idx = {i["name"] for i in insp.get_indexes("task_event")}
    if "uq_task_event_run_seq" in idx:
        op.drop_index("uq_task_event_run_seq", table_name="task_event")
    if "ix_task_event_run_id" not in idx:
        op.create_index("ix_task_event_run_id", "task_event", ["run_id"])
