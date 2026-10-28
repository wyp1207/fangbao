"""迁移 0025：设备接入凭证与防重放 nonce 表。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("device_credential"):
        op.create_table(
            "device_credential",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("robot_id", sa.Integer, nullable=False, index=True),
            sa.Column("key_id", sa.String(64), nullable=False, unique=True, index=True),
            sa.Column("secret_enc", sa.String(256), nullable=False),
            sa.Column("enabled", sa.Boolean, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime),
            sa.Column("last_used_at", sa.DateTime),
            sa.Column("revoked_at", sa.DateTime),
        )
    if not insp.has_table("device_nonce"):
        op.create_table(
            "device_nonce",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("key_id", sa.String(64), nullable=False, index=True),
            sa.Column("nonce", sa.String(64), nullable=False),
            sa.Column("ts", sa.Integer, nullable=False),
            sa.Column("created_at", sa.DateTime),
            sa.UniqueConstraint("key_id", "nonce", name="uq_device_nonce"),
        )


def downgrade() -> None:
    pass
