"""把开发库补齐到当前模型（仅限 sqlite 开发环境）。

为什么需要：开发库是 create_all 建的，后来加了列只改了模型；
alembic 在已有库上跑不动（0001 会重复建表）。生产走 alembic，开发用这个补。
用法：python tools_sync_dev_schema.py
"""

from __future__ import annotations

import sys

from sqlalchemy import inspect, text

from app.db.session import Base, engine
import app.models  # noqa: F401  触发模型注册


def main() -> int:
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    added: list[str] = []

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing:
                table.create(conn)
                added.append(f"+ 表 {table.name}")
                continue
            cols = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in cols:
                    continue
                ddl = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}'
                if col.server_default is not None:
                    ddl += " DEFAULT " + str(col.server_default.arg)
                conn.execute(text(ddl))
                added.append(f"+ {table.name}.{col.name}")

    print("\n".join(added) if added else "已是最新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
