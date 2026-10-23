"""把本机演示数据同步到另一套库（告警/工单/消息/审计）。

为什么不用 mysqldump：两边库型不同（本机 SQLite、现场 MySQL），
直接导 SQL 会踩方言差异。这里只搬"业务数据"，用 ORM 走同一套模型，
按 id upsert（存在就覆盖字段，不存在就插入），可重复执行。

用法：
    # 1) 本机导出
    python tools_sync_demo_data.py export --out /tmp/demo.json
    # 2) 目标机导入（容器内执行）
    docker cp /tmp/demo.json jc-server:/tmp/demo.json
    docker exec jc-server python tools_sync_demo_data.py import --in /tmp/demo.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime

TABLES = ("alarm_record", "work_order", "message_record", "inspection_task",
          "inspection_item", "task_run", "task_run_step")


def _dump(db, table: str) -> list[dict]:
    from sqlalchemy import text

    rows = db.execute(text(f"SELECT * FROM {table}")).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, datetime):
                d[k] = {"__dt__": v.isoformat(timespec="seconds")}
        out.append(d)
    return out


def _load(db, table: str, rows: list[dict]) -> int:
    from sqlalchemy import text

    model = {
        "alarm_record": "app.models.alarm:AlarmRecord",
        "work_order": "app.models.inspection:WorkOrder",
        "message_record": "app.models.message:MessageRecord",
        "inspection_task": "app.models.inspection:InspectionTask",
        "inspection_item": "app.models.inspection:InspectionItem",
        "task_run": "app.models.task_run:TaskRun",
        "task_run_step": "app.models.task_run:TaskRunStep",
    }[table]
    mod, cls = model.split(":")
    module = __import__(mod, fromlist=[cls])
    Model = getattr(module, cls)

    n = 0
    for r in rows:
        clean = {k: (datetime.fromisoformat(v["__dt__"]) if isinstance(v, dict) and "__dt__" in v else v)
                 for k, v in r.items()}
        obj = db.get(Model, clean.get("id"))
        if obj is None:
            db.add(Model(**clean))
        else:
            for k, v in clean.items():
                if k != "id":
                    setattr(obj, k, v)
        n += 1
    db.commit()
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["export", "import"])
    ap.add_argument("--out", default="demo_data.json")
    ap.add_argument("--in", dest="inp", default="demo_data.json")
    args = ap.parse_args()

    from app.db.session import SessionLocal

    if args.mode == "export":
        with SessionLocal() as db:
            data = {t: _dump(db, t) for t in TABLES}
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        print("导出:", {k: len(v) for k, v in data.items()})
        return 0

    with open(args.inp, encoding="utf-8") as f:
        data = json.load(f)
    with SessionLocal() as db:
        for t in TABLES:
            rows = data.get(t) or []
            if rows:
                print(f"  {t}: 导入 {len(rows)} 行 → {_load(db, t, rows)}")
    print("导入完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
