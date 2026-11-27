"""迁移 0032：视频源显式大屏角色（none/visible/thermal）。

旧逻辑只有一个 show_on_dashboard 布尔 + 按名字猜可见光/热红外，两路经常选到同一路。
新逻辑由用户在摄像头管理里直接指定“可见光 / 热红外”，首页只认这个字段。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("video_source"):
        return
    cols = {c["name"] for c in insp.get_columns("video_source")}
    if "dashboard_role" not in cols:
        op.add_column(
            "video_source",
            sa.Column("dashboard_role", sa.String(16), nullable=False, server_default="none"),
        )
    # 旧数据：勾了首页的按名字回填；热成像归 thermal，其余归 visible
    op.execute(
        "UPDATE video_source SET dashboard_role = CASE "
        "WHEN show_on_dashboard = 1 AND ("
        "name LIKE '%热%' OR name LIKE '%红外%' OR stream_name LIKE '%thermal%'"
        ") THEN 'thermal' "
        "WHEN show_on_dashboard = 1 THEN 'visible' "
        "ELSE 'none' END"
    )
    idx = {i["name"] for i in insp.get_indexes("video_source")}
    if "ix_video_source_dashboard_role" not in idx:
        op.create_index("ix_video_source_dashboard_role", "video_source", ["dashboard_role"])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("video_source"):
        return
    idx = {i["name"] for i in insp.get_indexes("video_source")}
    if "ix_video_source_dashboard_role" in idx:
        op.drop_index("ix_video_source_dashboard_role", table_name="video_source")
    cols = {c["name"] for c in insp.get_columns("video_source")}
    if "dashboard_role" in cols:
        op.drop_column("video_source", "dashboard_role")
