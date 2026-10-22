"""清理告警/工单存量（一次性，幂等，可预演）。

背景：告警去重修复前，一台离线设备每分钟新增一条，留了 174 条告警、142 张工单。
清理原则（不要直接 DELETE，审计要能解释每一行为什么被关）：
- 同一机器人同一指标，保留最新一条未关闭告警，其余写 resolved_at + resolution=重复合并；
- 工单：同一告警来源（meta 里的 alarm_id）保留最早一张，其余待派单的置 cancelled；
- 已有处置记录（handled_at/closed_at）的一律不动。

用法：
    python tools_clean_alarm_stock.py            # 预演，只打印
    python tools_clean_alarm_stock.py --apply    # 真执行
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime

from app.db.session import SessionLocal
from app.models.alarm import AlarmRecord
from app.models.inspection import WorkOrder


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    now = datetime.now()

    with SessionLocal() as db:
        open_rows = (db.query(AlarmRecord)
                     .filter(AlarmRecord.resolved_at.is_(None),
                             AlarmRecord.closed_at.is_(None))
                     .order_by(AlarmRecord.id).all())
        groups: dict[tuple, list[AlarmRecord]] = defaultdict(list)
        for a in open_rows:
            groups[(a.robot_id, a.metric)].append(a)

        dupes: list[AlarmRecord] = []
        for (_robot, _metric), rows in groups.items():
            rows.sort(key=lambda r: r.started_at or now)
            # 保留最新一条，其余合并关闭（有确认/处置痕迹的跳过）
            for old in rows[:-1]:
                if old.acked_at or old.handled_at or old.closed_at:
                    continue
                dupes.append(old)

        print(f"未关闭告警 {len(open_rows)} 条，可合并 {len(dupes)} 条")
        for a in dupes[:5]:
            print(f"  合并 #{a.id} {a.metric} robot={a.robot_id} {a.message[:24]}")

        pending = (db.query(WorkOrder)
                   .filter(WorkOrder.status.in_(("pending", "open", "assigned")))
                   .order_by(WorkOrder.id).all())
        # 用来源告警的 metric 做去重键：标题里带"第 N 次"所以标题去重无效
        alarm_metric = {a.id: a.metric for a in db.query(AlarmRecord).all()}
        seen: set[str] = set()
        cancel: list[WorkOrder] = []
        for o in pending:
            if o.assignee_id or o.status == "closed":
                continue
            key = alarm_metric.get(o.source_id or -1) or (o.title or "").split("（")[0]
            if key in seen:
                cancel.append(o)
            else:
                seen.add(key)
        print(f"待派工单 {len(pending)} 张，可取消重复 {len(cancel)} 张")
        for o in cancel[:5]:
            print(f"  取消 #{o.id} {o.title[:24]}")

        if not args.apply:
            print("\n预演结束。加 --apply 真执行。")
            return 0

        for a in dupes:
            a.resolved_at = now
            a.resolution = "重复合并：同指标已有更新的告警"
        for o in cancel:
            o.status = "closed"          # 工单状态只有 open/closed 两种
            o.resolution = "存量清理：同指标重复工单，已合并"
            o.closed_at = now
        db.commit()
        print(f"\n已合并告警 {len(dupes)} 条，取消重复工单 {len(cancel)} 张")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
