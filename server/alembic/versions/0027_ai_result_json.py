"""迁移 0027：ai_result 增加 result_json（盒子原始记录 + 图片 URL）。

Phase 4 只存图片 URL、不下载原图；原始记录也要留档，便于后面补采/对账。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if "result_json" not in _cols("ai_result"):
        op.add_column("ai_result", sa.Column("result_json", sa.Text, nullable=True))


def downgrade() -> None:
    if "result_json" in _cols("ai_result"):
        with op.batch_alter_table("ai_result") as batch:
            batch.drop_column("result_json")
