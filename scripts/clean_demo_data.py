"""清理开发库里的联调测试数据（只删明显是测试造的数据，不动真实记录）。

跑法：python scripts/clean_demo_data.py --yes
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "server" / "data" / "app.db"
PATTERNS = ("联调-%", "联调计划%", "QA-%", "幂等验证%", "并发下发%", "并发审计%",
            "定位门验证%", "巡航E2E%", "锁测试%")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    if not args.yes:
        print("加 --yes 才执行")
        return 1
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    like = " OR ".join(["name LIKE ?"] * len(PATTERNS))
    names = [p.replace("-", "-") for p in PATTERNS]

    sensors = con.execute(f"SELECT id, name FROM sensor WHERE {like}", names).fetchall()
    runs = con.execute(
        "SELECT id, name FROM task_run WHERE name LIKE '联调%' OR name LIKE '并发%' "
        "OR name LIKE '幂等%' OR name LIKE '巡航E2E%'").fetchall()
    tpls = con.execute("SELECT id, name FROM task_template WHERE name LIKE '联调%'").fetchall()
    plans = con.execute("SELECT id, name FROM inspection_plan WHERE name LIKE '联调%'").fetchall()

    for s in sensors:
        con.execute("DELETE FROM sensor_reading WHERE sensor_id=?", (s["id"],))
        con.execute("DELETE FROM sensor WHERE id=?", (s["id"],))
    for r in runs:
        con.execute("DELETE FROM task_run_step WHERE run_id=?", (r["id"],))
        con.execute("DELETE FROM task_run WHERE id=?", (r["id"],))
    for t in tpls:
        con.execute("DELETE FROM task_template WHERE id=?", (t["id"],))
    for p in plans:
        con.execute("DELETE FROM inspection_plan WHERE id=?", (p["id"],))
    con.execute("DELETE FROM alarm_record WHERE message LIKE '%联调%'")
    con.commit()
    print("清理完成：")
    print("  传感器", len(sensors), [s["name"] for s in sensors][:5])
    print("  任务", len(runs), [r["name"] for r in runs][:5])
    print("  模板", len(tpls), "计划", len(plans))
    left = con.execute("SELECT count(*) c FROM alarm_record WHERE acked_at IS NULL "
                       "AND closed_at IS NULL").fetchone()["c"]
    print("  仍未确认/未关闭的告警：", left)
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
