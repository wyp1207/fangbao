"""重建审计哈希链（仅 dev/维护用，生产慎用）。

并发写导致链断裂（prev_hash 重复）后，按 id 顺序重算一次即可恢复自洽。
用法：python scripts/repair_audit_chain.py --yes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from app.db.session import SessionLocal  # noqa: E402
from app.models.operation_log import OperationLog  # noqa: E402
from app.services.messages import _row_hash, verify_audit_chain  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="确认要重写全部哈希")
    args = ap.parse_args()
    if not args.yes:
        print("加 --yes 才会执行（会重写历史哈希）")
        return 1
    with SessionLocal() as db:
        rows = db.query(OperationLog).order_by(OperationLog.id).all()
        prev = None
        n = 0
        for r in rows:
            r.prev_hash = prev
            r.row_hash = _row_hash(prev, r)
            prev = r.row_hash
            n += 1
        db.commit()
        print(f"重建 {n} 行")
        print("复验：", verify_audit_chain(db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
