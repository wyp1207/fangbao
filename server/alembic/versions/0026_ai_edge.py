"""迁移 0026：AI 边缘接入（结果补列 + 流/预置位/复核/样本表）。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())

    if insp.has_table("ai_result"):
        cols = _cols("ai_result")
        add = [
            ("source_id", sa.Integer),
            ("external_event_id", sa.String(64)),
            ("preset_id", sa.Integer),
            ("stream_type", sa.String(16)),
            ("pan", sa.Float),
            ("tilt", sa.Float),
            ("zoom", sa.Float),
            ("review_state", sa.String(16)),
            ("diagnosis_json", sa.Text),
            ("evidence_clip", sa.String(255)),
        ]
        for name, typ in add:
            if name not in cols:
                op.add_column("ai_result", sa.Column(name, typ, nullable=True))
        # 唯一键：source_id + external_event_id（SQLite/MySQL 均允许多个 NULL）
        idx = {i["name"] for i in insp.get_indexes("ai_result")}
        if "uq_ai_result_event" not in idx:
            op.create_index(
                "uq_ai_result_event", "ai_result",
                ["source_id", "external_event_id"], unique=True,
            )

    if not insp.has_table("ai_source"):
        op.create_table(
            "ai_source",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(64), nullable=False, unique=True),
            sa.Column("base_url", sa.String(255), nullable=False),
            sa.Column("vendor", sa.String(32), server_default="crip"),
            sa.Column("auth_type", sa.String(16), server_default="openapi"),
            sa.Column("auth_ref", sa.String(64), server_default=""),
            sa.Column("poll_interval_s", sa.Integer, server_default="5"),
            sa.Column("enabled", sa.Boolean, server_default=sa.text("1")),
            sa.Column("last_poll_at", sa.DateTime),
            sa.Column("last_error", sa.String(255)),
            sa.Column("created_at", sa.DateTime),
        )

    if not insp.has_table("ai_stream"):
        op.create_table(
            "ai_stream",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("robot_id", sa.Integer, nullable=False, index=True),
            sa.Column("stream_type", sa.String(16), nullable=False),
            sa.Column("role", sa.String(8), server_default="main"),
            sa.Column("rtsp_url", sa.String(512), server_default=""),
            sa.Column("channel", sa.String(8)),
            sa.Column("resolution", sa.String(16)),
            sa.Column("fps", sa.Integer),
            sa.Column("codec", sa.String(16)),
            sa.Column("status", sa.String(16), server_default="active"),
            sa.Column("note", sa.String(128)),
            sa.Column("created_at", sa.DateTime),
            sa.UniqueConstraint("robot_id", "stream_type", "role", name="uq_ai_stream_role"),
        )

    if not insp.has_table("ai_preset_rule"):
        op.create_table(
            "ai_preset_rule",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("stream_id", sa.Integer, nullable=False, index=True),
            sa.Column("preset_id", sa.Integer, nullable=False),
            sa.Column("preset_name", sa.String(32), server_default=""),
            sa.Column("pan", sa.Float),
            sa.Column("tilt", sa.Float),
            sa.Column("zoom", sa.Float),
            sa.Column("tolerance_deg", sa.Float, server_default="2.0"),
            sa.Column("dwell_s", sa.Integer, server_default="20"),
            sa.Column("roi_json", sa.Text),
            sa.Column("algorithm_ids", sa.String(255)),
            sa.Column("enabled", sa.Boolean, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime),
            sa.UniqueConstraint("stream_id", "preset_id", name="uq_ai_preset_rule"),
        )

    if not insp.has_table("ai_review"):
        op.create_table(
            "ai_review",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("result_id", sa.Integer, nullable=False, index=True),
            sa.Column("reviewer", sa.String(64), server_default=""),
            sa.Column("state", sa.String(16), server_default="confirmed"),
            sa.Column("note", sa.String(255)),
            sa.Column("created_at", sa.DateTime),
        )

    if not insp.has_table("ai_sample_label"):
        op.create_table(
            "ai_sample_label",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("result_id", sa.Integer, index=True),
            sa.Column("label", sa.String(8), nullable=False),
            sa.Column("reason", sa.String(128)),
            sa.Column("labeled_by", sa.String(64), server_default=""),
            sa.Column("created_at", sa.DateTime),
        )


def downgrade() -> None:
    # 只删本迁移新增的表；ai_result 的列保留（避免丢数据）
    for table in ("ai_sample_label", "ai_review", "ai_preset_rule", "ai_stream", "ai_source"):
        try:
            op.drop_table(table)
        except Exception:  # noqa: BLE001
            pass
