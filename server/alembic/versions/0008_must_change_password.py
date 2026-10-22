"""强制改密标记

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-22

背景：初始管理员密码是部署脚本生成的，客户往往不改就一直用；
等保测评也会问"初始密码是否强制修改"。这里加一个标记，前端登录后强制弹改密框。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("user"):
        return
    cols = {c["name"] for c in insp.get_columns("user")}
    if "must_change_password" not in cols:
        op.add_column(
            "user",
            sa.Column("must_change_password", sa.Boolean, server_default=sa.false()),
        )


def downgrade() -> None:
    pass
