"""多设备 / 告警 / 消息 / 设置 / 传感器 / 遥测 / 录制计划 / 地图库

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-21

这一版把"接真机即可用"所需的表一次补齐：
- robot 增加设备台账字段（类型/协议/场站/账号/密码密文/备注）
- alarm_record：告警持久化 + 处置闭环字段
- message_record：消息中心持久化
- setting：平台设置
- sensor / sensor_reading：环境传感器与读数
- telemetry_sample：运行数据采样
- record_plan：定时录制计划
- platform_map / point_draft：平台地图库与点位草稿

全部使用 IF NOT EXISTS 语义（先查存在性），因为老环境可能已经用 create_all 建过表。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def _cols(table: str) -> set[str]:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(table):
        return set()
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    # ---------- robot：设备台账字段 ----------
    robot_cols = _cols("robot")
    add_robot = {
        "device_type": sa.Column("device_type", sa.String(32), server_default="jcrob_wheel"),
        "adapter": sa.Column("adapter", sa.String(32), server_default="jcrob_http"),
        "station": sa.Column("station", sa.String(64), server_default="默认场站"),
        "username": sa.Column("username", sa.String(64), nullable=True),
        "password_cipher": sa.Column("password_cipher", sa.Text, nullable=True),
        "note": sa.Column("note", sa.String(200), nullable=True),
    }
    for name, col in add_robot.items():
        if name not in robot_cols:
            op.add_column("robot", col)

    # ---------- video_source ----------
    # 基线 0001 只建了 user/robot/operation_log，摄像头表一直靠 dev 的 create_all，
    # 生产库必须在这里补上，否则视频/录制计划接口直接 500
    if not _has_table("video_source"):
        op.create_table(
            "video_source",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("group_name", sa.String(32), server_default="默认分组"),
            sa.Column("vendor", sa.String(16), server_default="other"),
            sa.Column("url", sa.String(512), nullable=False),
            sa.Column("stream_name", sa.String(32), server_default=""),
            sa.Column("enabled", sa.Boolean, server_default=sa.true()),
            sa.Column("note", sa.String(200), nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )
        log_hint = True

    # ---------- alarm_record ----------
    if not _has_table("alarm_record"):
        op.create_table(
            "alarm_record",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("metric", sa.String(32), nullable=False),
            sa.Column("level", sa.String(16), nullable=False),
            sa.Column("message", sa.String(255), nullable=False),
            sa.Column("value_json", sa.Text, nullable=True),
            sa.Column("started_at", sa.DateTime, server_default=sa.func.now()),
            sa.Column("acked_at", sa.DateTime, nullable=True),
            sa.Column("acked_by", sa.String(64), nullable=True),
            sa.Column("robot_id", sa.Integer, nullable=True),
            sa.Column("camera_id", sa.Integer, nullable=True),
            sa.Column("meta_json", sa.Text, nullable=True),
            sa.Column("handled_at", sa.DateTime, nullable=True),
            sa.Column("handled_by", sa.String(64), nullable=True),
            sa.Column("handle_note", sa.Text, nullable=True),
            sa.Column("closed_at", sa.DateTime, nullable=True),
            sa.Column("closed_by", sa.String(64), nullable=True),
            sa.Column("resolution", sa.String(32), nullable=True),
            sa.Column("close_note", sa.Text, nullable=True),
        )
        op.create_index("ix_alarm_record_metric", "alarm_record", ["metric"])
        op.create_index("ix_alarm_record_level", "alarm_record", ["level"])
        op.create_index("ix_alarm_record_started_at", "alarm_record", ["started_at"])

    # ---------- message_record ----------
    if not _has_table("message_record"):
        op.create_table(
            "message_record",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("ts", sa.DateTime, server_default=sa.func.now()),
            sa.Column("level", sa.String(16), server_default="info"),
            sa.Column("source", sa.String(16), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("body", sa.Text, nullable=True),
            sa.Column("link_json", sa.Text, nullable=True),
        )
        op.create_index("ix_message_record_ts", "message_record", ["ts"])
        op.create_index("ix_message_record_source", "message_record", ["source"])

    # ---------- setting ----------
    if not _has_table("setting"):
        op.create_table(
            "setting",
            sa.Column("key", sa.String(64), primary_key=True),
            sa.Column("value_json", sa.Text, nullable=False),   # MySQL 的 TEXT 不能带 DEFAULT
            sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
            sa.Column("updated_by", sa.String(64), nullable=True),
            sa.Column("note", sa.String(200), nullable=True),
            sa.Column("version", sa.Integer, server_default="1"),
        )

    # ---------- sensor ----------
    if not _has_table("sensor"):
        op.create_table(
            "sensor",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("kind", sa.String(24), nullable=False),
            sa.Column("unit", sa.String(16), server_default=""),
            sa.Column("station", sa.String(64), server_default="默认场站"),
            sa.Column("location", sa.String(128), nullable=True),
            sa.Column("serial", sa.String(64), nullable=True),
            sa.Column("warn_low", sa.Float, nullable=True),
            sa.Column("warn_high", sa.Float, nullable=True),
            sa.Column("crit_low", sa.Float, nullable=True),
            sa.Column("crit_high", sa.Float, nullable=True),
            sa.Column("enabled", sa.Boolean, server_default=sa.true()),
            sa.Column("note", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )
        op.create_index("ix_sensor_kind", "sensor", ["kind"])

    if not _has_table("sensor_reading"):
        op.create_table(
            "sensor_reading",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("sensor_id", sa.Integer, nullable=False),
            sa.Column("ts", sa.DateTime, server_default=sa.func.now()),
            sa.Column("value", sa.Float, nullable=False),
            sa.Column("source", sa.String(24), server_default="manual"),
        )
        op.create_index("ix_sensor_reading_sensor_id", "sensor_reading", ["sensor_id"])
        op.create_index("ix_sensor_reading_ts", "sensor_reading", ["ts"])

    # ---------- telemetry_sample ----------
    if not _has_table("telemetry_sample"):
        op.create_table(
            "telemetry_sample",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("robot_id", sa.Integer, nullable=False, server_default="1"),
            sa.Column("ts", sa.DateTime, server_default=sa.func.now()),
            sa.Column("battery", sa.Float, nullable=True),
            sa.Column("voltage", sa.Float, nullable=True),
            sa.Column("speed", sa.Float, nullable=True),
            sa.Column("yaw_rate", sa.Float, nullable=True),
            sa.Column("x", sa.Float, nullable=True),
            sa.Column("y", sa.Float, nullable=True),
            sa.Column("theta", sa.Float, nullable=True),
            sa.Column("online", sa.Boolean, server_default=sa.false()),
            sa.Column("estop", sa.Boolean, server_default=sa.false()),
        )
        op.create_index("ix_telemetry_sample_robot_id", "telemetry_sample", ["robot_id"])
        op.create_index("ix_telemetry_sample_ts", "telemetry_sample", ["ts"])

    # ---------- record_plan ----------
    if not _has_table("record_plan"):
        op.create_table(
            "record_plan",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("video_id", sa.Integer, nullable=False),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("days", sa.String(7), server_default="1111111"),
            sa.Column("start_time", sa.String(5), server_default="00:00"),
            sa.Column("end_time", sa.String(5), server_default="23:59"),
            sa.Column("enabled", sa.Boolean, server_default=sa.true()),
            sa.Column("note", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )
        op.create_index("ix_record_plan_video_id", "record_plan", ["video_id"])

    # ---------- platform_map ----------
    if not _has_table("platform_map"):
        op.create_table(
            "platform_map",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("floor", sa.String(32), server_default="1F"),
            sa.Column("station", sa.String(64), server_default="默认场站"),
            sa.Column("resolution", sa.Float, server_default="0.05"),
            sa.Column("origin_x", sa.Float, server_default="0"),
            sa.Column("origin_y", sa.Float, server_default="0"),
            sa.Column("origin_theta", sa.Float, server_default="0"),
            sa.Column("image_path", sa.String(255), nullable=False),
            sa.Column("width", sa.Integer, server_default="0"),
            sa.Column("height", sa.Integer, server_default="0"),
            sa.Column("robot_map_name", sa.String(64), nullable=True),
            sa.Column("is_active", sa.Boolean, server_default=sa.true()),
            sa.Column("note", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )

    if not _has_table("point_draft"):
        op.create_table(
            "point_draft",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("map_id", sa.Integer, nullable=False),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("x", sa.Float, nullable=False),
            sa.Column("y", sa.Float, nullable=False),
            sa.Column("theta", sa.Float, server_default="0"),
            sa.Column("note", sa.String(200), nullable=True),
            sa.Column("synced", sa.Boolean, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )
        op.create_index("ix_point_draft_map_id", "point_draft", ["map_id"])


def downgrade() -> None:
    for name in ("point_draft", "platform_map", "record_plan", "telemetry_sample",
                 "sensor_reading", "sensor", "setting", "message_record", "alarm_record",
                 "video_source"):
        if _has_table(name):
            op.drop_table(name)
