"""备份恢复演练：把备份还原到一个临时库，校验数据与审计链。"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUPS = ROOT / "server" / "data" / "backups"
latest = sorted(BACKUPS.glob("app-*.db"))[-1]
tmp = Path(tempfile.gettempdir()) / "restore-drill.db"
if tmp.exists():
    tmp.unlink()

env = dict(os.environ)
env["JC_DB_URL"] = "sqlite:///" + tmp.as_posix()
subprocess.run([sys.executable, str(ROOT / "scripts" / "backup_db.py"), "restore", str(latest)],
               env=env, check=True)

with sqlite3.connect(tmp) as con:
    runs = con.execute("SELECT count(*) FROM task_run").fetchone()[0]
    logs = con.execute("SELECT count(*) FROM operation_log").fetchone()[0]
    order = con.execute("SELECT count(*) FROM task_run WHERE order_id IS NOT NULL").fetchone()[0]
print(f"恢复后：task_run={runs} operation_log={logs} 有 order_id 的任务={order}")

sys.path.insert(0, str(ROOT / "server"))
os.environ["JC_DB_URL"] = env["JC_DB_URL"]
from app.db.session import SessionLocal  # noqa: E402
from app.services.messages import verify_audit_chain  # noqa: E402

with SessionLocal() as db:
    print("审计链校验：", verify_audit_chain(db))
print("演练完成，临时库：", tmp)
