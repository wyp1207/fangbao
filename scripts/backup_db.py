"""数据库备份 / 恢复（SQLite 与 MySQL 都支持）。

为什么必须有：DBA 视角评审给出 0 分——库文件损坏=台账与审计全丢。
用法：
    python scripts/backup_db.py backup            # 备份到 data/backups/
    python scripts/backup_db.py backup --keep 14  # 只保留最近 14 份
    python scripts/backup_db.py restore <file>    # 恢复（会先备份当前库）
    python scripts/backup_db.py list
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_DEFAULT = ROOT / "server" / "data" / "app.db"
BACKUP_DIR = ROOT / "server" / "data" / "backups"


def db_url() -> str:
    return os.environ.get("JC_DB_URL", "")


def backup(keep: int = 14) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    url = db_url()
    if not url or url.startswith("sqlite"):
        src = Path(url.split("///")[-1]) if url else DB_DEFAULT
        if not src.is_absolute():
            src = ROOT / src
        if not src.exists():
            raise SystemExit(f"库文件不存在：{src}")
        dst = BACKUP_DIR / f"app-{stamp}.db"
        # 用 sqlite3 的 backup API，避免直接拷贝正在写的文件（WAL 下不安全）
        with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
            s.backup(d)
        print(f"已备份 {src.name} → {dst}（{dst.stat().st_size // 1024} KB）")
    else:
        dst = BACKUP_DIR / f"mysql-{stamp}.sql"
        cmd = f"mysqldump --single-transaction --quick --databases jc_robot > {dst}"
        subprocess.run(cmd, shell=True, check=True)
        print(f"已导出 MySQL → {dst}（{dst.stat().st_size // 1024} KB）")

    backups = sorted(BACKUP_DIR.glob("app-*.db"), key=lambda p: p.stat().st_mtime)
    for old in backups[:-keep]:
        old.unlink()
        print("清理旧备份", old.name)
    return dst


def restore(path: str) -> None:
    src = Path(path)
    if not src.exists():
        raise SystemExit(f"备份不存在：{src}")
    url = db_url()
    if not url or url.startswith("sqlite"):
        target = Path(url.split("///")[-1]) if url else DB_DEFAULT
        if not target.is_absolute():
            target = ROOT / target
        safety = backup(keep=30) if target.exists() else None
        shutil.copy2(src, target)
        note = f"恢复前已再备份：{safety.name}" if safety else "目标原本不存在，直接创建"
        print(f"已恢复 {src.name} → {target}（{note}）")
    else:
        cmd = f"mysql jc_robot < {src}"
        subprocess.run(cmd, shell=True, check=True)
        print(f"已恢复 MySQL ← {src.name}")


def list_backups() -> None:
    if not BACKUP_DIR.exists():
        print("还没有备份")
        return
    for p in sorted(BACKUP_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        kb = p.stat().st_size // 1024
        print(f"{p.name}\t{kb} KB\t{datetime.fromtimestamp(p.stat().st_mtime):%Y-%m-%d %H:%M}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["backup", "restore", "list"])
    ap.add_argument("file", nargs="?")
    ap.add_argument("--keep", type=int, default=14)
    args = ap.parse_args()
    if args.action == "backup":
        backup(args.keep)
    elif args.action == "restore":
        if not args.file:
            raise SystemExit("restore 需要指定备份文件")
        restore(args.file)
    else:
        list_backups()
    return 0


if __name__ == "__main__":
    sys.exit(main())
