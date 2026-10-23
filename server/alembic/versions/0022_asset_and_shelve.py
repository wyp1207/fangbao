"""防爆资产台账字段 + 告警搁置

Revision ID: 0022
Revises: 0021
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

ROBOT_COLS = [
    ("asset_no", sa.String(64)),          # 资产编号（厂内位号）
    ("ex_marking", sa.String(64)),        # 防爆标志 Ex d IIB T4 Gb
    ("ex_cert_no", sa.String(64)),        # 防爆合格证号
    ("ex_cert_expiry", sa.Date()),        # 证书有效期
    ("ex_zone", sa.String(32)),           # 防爆区域 Zone 1/2
    ("owner", sa.String(32)),             # 设备责任人
    ("maint_due", sa.Date()),             # 下次维保
]

ALARM_COLS = [
    ("shelved_until", sa.DateTime()),
    ("shelve_reason", sa.String(200)),
    ("priority", sa.String(8)),           # P1..P4（ISA-18.2 式分级）
]


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())

    def cols(table: str) -> set[str]:
        return {c["name"] for c in insp.get_columns(table)} if insp.has_table(table) else set()

    if insp.has_table("robot"):
        have = cols("robot")
        for name, typ in ROBOT_COLS:
            if name not in have:
                op.add_column("robot", sa.Column(name, typ))

    if insp.has_table("alarm_record"):
        insp2 = sa.inspect(op.get_bind())
        have = {c["name"] for c in insp2.get_columns("alarm_record")}
        for name, typ in ALARM_COLS:
            if name not in have:
                op.add_column("alarm_record", sa.Column(name, typ))

        # 历史告警回填分级（列加完再 UPDATE）
        op.execute("""
            UPDATE alarm_record SET priority = CASE
              WHEN level='critical' AND (metric LIKE '%env_gas%' OR metric LIKE '%estop%'
                   OR metric LIKE '%smoke%' OR metric LIKE '%fire%') THEN 'P1'
              WHEN level='critical' THEN 'P2'
              WHEN level='warn' THEN 'P3'
              ELSE 'P4' END
            WHERE priority IS NULL
        """)


def downgrade() -> None:
    pass
