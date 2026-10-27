"""验证：来源告警被搁置时，工单不会被升级。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from app.db.session import SessionLocal
from app.services.work_orders import escalate_overdue

DB = r"D:\Desktop\防爆机器人\server\data\app.db"

con = sqlite3.connect(DB)
row = con.execute(
    "SELECT id, source_id, due_at FROM work_order WHERE source='alarm' AND status!='closed' LIMIT 1"
).fetchone()
if not row:
    print("没有可用的来源告警工单，跳过")
    raise SystemExit(0)
oid, aid, old_due = row
print(f"用工单 #{oid}（来源告警 #{aid}），原 due_at={old_due}")

past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
future = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")

con.execute("UPDATE work_order SET due_at=?, escalated_at=NULL WHERE id=?", (past, oid))
con.execute("UPDATE alarm_record SET shelved_until=?, shelve_reason='升级暂停测试' WHERE id=?",
            (future, aid))
con.commit()
con.close()

n = escalate_overdue(SessionLocal)
print(f"搁置中执行升级扫描 → 升级 {n} 条（期望 0）")

con = sqlite3.connect(DB)
con.execute("UPDATE alarm_record SET shelved_until=NULL, shelve_reason=NULL WHERE id=?", (aid,))
con.execute("UPDATE work_order SET due_at=?, escalated_at=NULL WHERE id=?", (old_due, oid))
con.commit()
con.close()
print("已恢复工单与告警原状态")
