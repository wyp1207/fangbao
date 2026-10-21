import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _has(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if not _has("notify_channel"):
        op.create_table(
            "notify_channel",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("type", sa.String(24), nullable=False),
            sa.Column("config_json", sa.Text, nullable=False, server_default="{}"),
            sa.Column("min_level", sa.String(16), server_default="critical"),
            sa.Column("min_interval_min", sa.Integer, server_default="10"),
            sa.Column("enabled", sa.Boolean, server_default=sa.true()),
            sa.Column("note", sa.String(200), nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )

    if not _has("notify_log"):
        op.create_table(
            "notify_log",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("ts", sa.DateTime, server_default=sa.func.now()),
            sa.Column("channel_id", sa.Integer, nullable=False),
            sa.Column("channel_name", sa.String(64), server_default=""),
            sa.Column("alarm_id", sa.Integer, nullable=True),
            sa.Column("payload", sa.Text, nullable=True),
            sa.Column("ok", sa.Boolean, server_default=sa.false()),
            sa.Column("status", sa.String(64), nullable=True),
            sa.Column("error", sa.Text, nullable=True),
        )
        op.create_index("ix_notify_log_ts", "notify_log", ["ts"])
        op.create_index("ix_notify_log_channel_id", "notify_log", ["channel_id"])


def downgrade() -> None:
    for name in ("notify_log", "notify_channel"):
        if _has(name):
            op.drop_table(name)
