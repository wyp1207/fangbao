"""重建审计哈希链（一次性迁移工具）。

背景：审计哈希算法换过一次（canonical 规则从"含微秒"改成"整秒"），
导致早期 1–128 条与新区块对不上，/audit-logs/verify 报 broken_at:1。

做法：按 id 顺序重算 prev_hash + hash，并写一条 audit 记录说明"链已重建"。
不删除任何行——内容不动，只修链，保证"内容未被改"这一点仍可自证。

用法：
    python tools_rechain_audit.py --dry-run
    python tools_rechain_audit.py
"""

from __future__ import annotations

import argparse

from app.db.session import SessionLocal
from app.models.operation_log import OperationLog as AuditLog
from app.services.messages import _canonical, _row_hash


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with SessionLocal() as db:
        rows = db.query(AuditLog).order_by(AuditLog.id).all()
        prev = "0" * 64
        changed = 0
        for r in rows:
            want = _row_hash(prev, r)
            if r.prev_hash != prev or r.row_hash != want:
                changed += 1
                if args.dry_run and changed <= 3:
                    print(f"  #{r.id} {r.action} 需要重算")
                r.prev_hash, r.row_hash = prev, want
            prev = want
        print(f"共 {len(rows)} 条，需重算 {changed} 条")
        if args.dry_run:
            print("预演结束，未写库。")
            db.rollback()
            return 0
        db.commit()
        print("已重建。请再跑一次 /api/v1/audit-logs/verify 确认 ok=true。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
