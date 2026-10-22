"""重算历史审计哈希链

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-22

背景：早期实现把 ts 的微秒也算进哈希，但 MySQL DATETIME 默认丢掉微秒，
导致校验时复算不一致、误报"内容被改"。这里按新规则（秒级）重建整条链。
"""

from __future__ import annotations

import hashlib

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def _canonical(row) -> str:
    return "|".join([
        str(row.ts.isoformat(timespec="seconds") if row.ts else ""),
        str(row.user_id or ""), str(row.username or ""), str(row.client_ip or ""),
        str(row.action or ""), str(row.target or ""),
        str(row.params_json or ""), "1" if row.success else "0",
        str(row.result_summary or ""), str(row.duration_ms or ""),
    ])


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("operation_log"):
        return
    meta = sa.MetaData()
    log = sa.Table("operation_log", meta, autoload_with=bind)

    rows = bind.execute(sa.select(log).order_by(log.c.id)).fetchall()
    prev = None
    for row in rows:
        sm = sa.select(log).where(log.c.id == row.id).execution_options(synchronize_session=False)
        obj = type("R", (), {})()
        for key in ("ts", "user_id", "username", "client_ip", "action", "target",
                    "params_json", "success", "result_summary", "duration_ms"):
            setattr(obj, key, getattr(row, key))
        digest = hashlib.sha256(((prev or "") + "|" + _canonical(obj)).encode()).hexdigest()
        bind.execute(sa.update(log).where(log.c.id == row.id)
                     .values(prev_hash=prev, row_hash=digest))
        prev = digest


def downgrade() -> None:
    pass
