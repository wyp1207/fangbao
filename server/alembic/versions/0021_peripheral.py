"""外设实例表 + 从现有 sensor/video_source 回填

Revision ID: 0021
Revises: 0020
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("peripheral"):
        op.create_table(
            "peripheral",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("robot_id", sa.Integer, index=True),
            sa.Column("kind", sa.String(32), index=True, nullable=False),
            sa.Column("vendor", sa.String(32)),
            sa.Column("model", sa.String(64)),
            sa.Column("channel", sa.String(32)),
            sa.Column("config_json", sa.Text),
            sa.Column("sensor_id", sa.Integer),
            sa.Column("video_id", sa.Integer),
            sa.Column("enabled", sa.Boolean, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )

    # ---- 回填：只增不删，旧表原样保留 ----
    conn = op.get_bind()
    has_robot = insp.has_table("robot")
    if not has_robot:
        return

    # 传感器 → peripheral（kind 直接用 sensor.kind，噪声/粉尘也能落进来）
    conn.execute(sa.text("""
        INSERT INTO peripheral (robot_id, kind, vendor, model, channel, config_json, sensor_id, enabled, created_at)
        SELECT s.robot_id,
               CASE WHEN s.kind IN ('gas','env','noise','dust','temperature','humidity','pm')
                    THEN s.kind ELSE 'env' END,
               'generic', NULL, s.serial,
               json_object('unit', s.unit, 'name', s.name),
               s.id, 1, CURRENT_TIMESTAMP
        FROM sensor s
        WHERE s.robot_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM peripheral p WHERE p.sensor_id = s.id)
    """))

    # 视频源 → peripheral（名字里带热/红外的算热像仪，其余算云台可见光）
    conn.execute(sa.text("""
        INSERT INTO peripheral (robot_id, kind, vendor, model, channel, config_json, video_id, enabled, created_at)
        SELECT v.robot_id,
               CASE WHEN lower(v.name) LIKE '%热%' OR lower(v.name) LIKE '%红外%' OR lower(v.name) LIKE '%thermal%'
                    THEN 'thermal' ELSE 'camera' END,
               COALESCE(v.vendor, 'generic'), NULL, v.stream_name,
               json_object('url', v.url, 'name', v.name),
               v.id, 1, CURRENT_TIMESTAMP
        FROM video_source v
        WHERE v.robot_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM peripheral p WHERE p.video_id = v.id)
    """))

    # 设备动作能力（本体能力，不来自外设）：按适配器推断一次
    conn.execute(sa.text("""
        UPDATE robot SET capabilities_json = json_object(
            'navigate', 1
        )
        WHERE capabilities_json IS NULL
    """))


def downgrade() -> None:
    op.drop_table("peripheral")
