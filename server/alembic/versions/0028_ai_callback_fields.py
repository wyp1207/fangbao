"""迁移 0028：ai_result 增加真实回调（.170 webhook）的盒子侧字段。

为什么加这四列：
回调里只有盒子的 `camera_id=13` / `camera_name=dog-云台` / `algorithm_id=4`，
平台自己的相机台账 id 还没建立映射；原样留档才能对账、才能在下一步建告警时
把"盒子 13 号相机"翻成平台设备。`source_url` 存改写后的可下载地址，回看图片
不用再依赖盒子内网地址 172.16.8.2。

幂等：列已存在就跳过（开发库可能已手工补过列）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    cols = _cols("ai_result")
    add = [
        ("external_camera_id", sa.Integer),
        ("external_camera_name", sa.String(64)),
        ("external_algorithm_id", sa.Integer),
        ("source_url", sa.String(512)),
    ]
    for name, typ in add:
        if name not in cols:
            op.add_column("ai_result", sa.Column(name, typ, nullable=True))


def downgrade() -> None:
    cols = _cols("ai_result")
    with op.batch_alter_table("ai_result") as batch:
        for name in ("source_url", "external_algorithm_id",
                     "external_camera_name", "external_camera_id"):
            if name in cols:
                batch.drop_column(name)
