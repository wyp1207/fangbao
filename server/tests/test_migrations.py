"""迁移完整性检查：alembic 建出来的库必须和 ORM 模型一致。

为什么需要这条测试：
开发时用 sqlite + `ALTER TABLE` 手改很爽，但忘了写迁移，
本地永远发现不了，直到在客户机器上全新 MySQL 才报
"Unknown column ..."。这条测试用 alembic 从零建库，再和 Base.metadata 比对。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

SERVER_ROOT = Path(__file__).resolve().parents[1]


def test_migrations_match_models(tmp_path):
    db = tmp_path / "mig_check.db"
    env = dict(os.environ)
    env["JC_DB_URL"] = f"sqlite:///{db.as_posix()}"
    env["JC_ENV"] = "test"
    env["PYTHONPATH"] = str(SERVER_ROOT)

    r = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=SERVER_ROOT, env=env, capture_output=True, text=True,
    )
    assert r.returncode == 0, f"迁移失败:\n{r.stdout}\n{r.stderr}"

    # 导入模型（必须在 alembic 之后，避免用到 app 的默认 DB）
    from app.db.session import Base
    import app.models  # noqa: F401  触发全部模型注册

    engine = create_engine(f"sqlite:///{db.as_posix()}")
    insp = inspect(engine)
    db_tables = set(insp.get_table_names())
    model_tables = set(Base.metadata.tables)

    missing_tables = model_tables - db_tables
    assert not missing_tables, f"迁移缺表：{sorted(missing_tables)}"

    problems: list[str] = []
    for table in sorted(model_tables):
        db_cols = {c["name"] for c in insp.get_columns(table)}
        model_cols = {c.name for c in Base.metadata.tables[table].columns}
        if model_cols - db_cols:
            problems.append(f"{table}: 缺列 {sorted(model_cols - db_cols)}")
    assert not problems, "迁移与模型不一致：\n" + "\n".join(problems)
