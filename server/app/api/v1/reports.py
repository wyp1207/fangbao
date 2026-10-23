"""报表：周报/月报口径的汇总与导出。

统计口径写死在这里，不散落在前端：
- 告警"总数"按 started_at 落在区间内算
- 平均确认时长 = acked_at - started_at（只统计已确认的）
- 平均处置时长 = closed_at - started_at（只统计已关闭的）
- 在线率来自遥测采样（offline 样本占比），没采样就返回 null，不编数字
"""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_csrf, require_roles
from app.core.errors import PlatformError
from app.db.session import get_db
from app.models.alarm import AlarmRecord
from app.models.sensor import Sensor, SensorReading
from app.models.telemetry import TelemetrySample
from app.models.user import User

router = APIRouter(prefix="/reports", tags=["reports"])

LEVELS = {"critical": "严重", "warn": "提醒"}
RESOLUTIONS = {"handled": "已处理", "defect": "设备缺陷", "misreport": "误报", "ignored": "忽略"}


def _range(date_from: str | None, date_to: str | None) -> tuple[datetime, datetime]:
    if date_from and date_to:
        start = datetime.fromisoformat(date_from)
        end = datetime.fromisoformat(date_to) + timedelta(days=1)
    else:
        today = date.today()
        start = datetime.combine(today - timedelta(days=6), datetime.min.time())
        end = datetime.combine(today + timedelta(days=1), datetime.min.time())
    return start, end


def _safe_actions(t) -> list:
    import json as _json
    try:
        return _json.loads(t.actions_json or "[]")
    except Exception:  # noqa: BLE001
        return []


def _avg_seconds(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


# 报表汇总一次要扫告警/工单/遥测，实测 p95 3.1s（并发 10）。
# 报表不是实时数据，15 秒缓存换来页面秒开；跨天/换范围自然换 key。
_SUMMARY_CACHE: dict[tuple, tuple[float, dict]] = {}
# 单飞锁：20 个并发同时冷启动会把 SQLite/MySQL 拖死（实测 /health 也超时），
# 只让一个线程算，其余等它算完直接吃缓存。
_SUMMARY_LOCK = __import__("threading").Lock()
# 测试环境不缓存，否则用例之间会读到上一条用例的旧汇总
try:
    from app.core.config import get_settings as _gs

    _SUMMARY_TTL = 0.0 if _gs().env == "test" else 15.0
except Exception:  # noqa: BLE001
    _SUMMARY_TTL = 15.0


@router.get("/summary")
def summary(
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """报表汇总：一次要扫告警/工单/遥测（冷查询 ~2.4s）。

    并发策略（实测过：20 个并发同时冷算会把进程拖死、/health 也超时）：
    - 命中缓存直接返回；
    - 抢不到锁就返回旧缓存；连旧缓存都没有就 429，让客户端稍后再试；
    - 测试环境 TTL=0，不缓存。
    """
    import time as _time

    key = (date_from, date_to)
    hit = _SUMMARY_CACHE.get(key)
    if _SUMMARY_TTL > 0 and hit and _time.time() - hit[0] < _SUMMARY_TTL:
        return hit[1]

    if not _SUMMARY_LOCK.acquire(timeout=1.0):
        if hit:
            return hit[1]
        raise PlatformError("报表正在生成，请稍后重试", code="REPORT_BUSY", status_code=429)
    try:
        if _SUMMARY_TTL > 0:
            hit = _SUMMARY_CACHE.get(key)
            if hit and _time.time() - hit[0] < _SUMMARY_TTL:
                return hit[1]
        out = _summary_impl(date_from=date_from, date_to=date_to, db=db, user=user)
        if _SUMMARY_TTL > 0:
            _SUMMARY_CACHE[key] = (_time.time(), out)
        return out
    finally:
        _SUMMARY_LOCK.release()


def _summary_impl(
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    start, end = _range(date_from, date_to)

    alarms = db.scalars(
        select(AlarmRecord).where(AlarmRecord.started_at >= start, AlarmRecord.started_at < end)
    ).all()

    by_level = {"critical": 0, "warn": 0}
    by_metric: dict[str, int] = {}
    by_resolution: dict[str, int] = {}
    ack_durations: list[float] = []
    close_durations: list[float] = []
    acked = handled = closed = 0

    for a in alarms:
        by_level[a.level] = by_level.get(a.level, 0) + 1
        by_metric[a.metric] = by_metric.get(a.metric, 0) + 1
        if a.acked_at:
            acked += 1
            ack_durations.append((a.acked_at - a.started_at).total_seconds())
        if a.handled_at:
            handled += 1
        if a.closed_at:
            closed += 1
            close_durations.append((a.closed_at - a.started_at).total_seconds())
            if a.resolution:
                by_resolution[a.resolution] = by_resolution.get(a.resolution, 0) + 1

    # 每个传感器的有效阈值（外设规则优先）——供上面的超限统计用
    import json as _json

    from app.models.peripheral import Peripheral as _Periph

    sensor_thresholds: dict[int, dict] = {}
    for p in db.query(_Periph).filter(_Periph.sensor_id.isnot(None),
                                     _Periph.enabled.is_(True)).all():
        try:
            rule = (_json.loads(p.config_json or "{}") or {}).get("rule") or {}
        except Exception:  # noqa: BLE001
            rule = {}
        if rule:
            sensor_thresholds[p.sensor_id] = {
                "enabled": rule.get("enabled", True),
                "warn_high": rule.get("warn_high"),
                "crit_high": rule.get("crit_high"),
                "warn_low": rule.get("warn_low"),
                "crit_low": rule.get("crit_low"),
            }

    # 环境：区间内每条传感器的读数
    readings = db.scalars(
        select(SensorReading).where(SensorReading.ts >= start, SensorReading.ts < end)
    ).all()
    sensors = {s.id: s for s in db.query(Sensor).all()}
    env_stats: dict[int, dict] = {}
    for r in readings:
        s = sensors.get(r.sensor_id)
        if not s:
            continue
        st = env_stats.setdefault(s.id, {
            "name": s.name, "kind": s.kind, "unit": s.unit, "count": 0,
            "min": r.value, "max": r.value, "over": 0,
        })
        st["count"] += 1
        st["min"] = min(st["min"], r.value)
        st["max"] = max(st["max"], r.value)
        # 与报警口径一致：外设规则优先，其次传感器自身阈值
        eff = sensor_thresholds.get(s.id) or {
            "warn_high": s.warn_high, "crit_high": s.crit_high,
            "warn_low": s.warn_low, "crit_low": s.crit_low, "enabled": True,
        }
        if eff.get("enabled", True) and (
            (eff.get("crit_high") is not None and r.value >= eff["crit_high"]) or
            (eff.get("warn_high") is not None and r.value >= eff["warn_high"]) or
            (eff.get("crit_low") is not None and r.value <= eff["crit_low"]) or
            (eff.get("warn_low") is not None and r.value <= eff["warn_low"])
        ):
            st["over"] += 1

    # 遥测：在线率/里程/电量
    samples = db.scalars(
        select(TelemetrySample).where(TelemetrySample.ts >= start, TelemetrySample.ts < end)
    ).all()
    batteries = [s.battery for s in samples if s.battery is not None]
    distance = 0.0
    prev = None
    for s in samples:
        if s.x is None or s.y is None:
            prev = None
            continue
        if prev:
            d = ((s.x - prev[0]) ** 2 + (s.y - prev[1]) ** 2) ** 0.5
            if d < 5:
                distance += d
        prev = (s.x, s.y)
    online_ratio = (
        round(sum(1 for s in samples if s.online) / len(samples) * 100, 1) if samples else None
    )

    # 按设备统计（多机器人后有意义）
    by_robot: dict[int, int] = {}
    for a in alarms:
        rid = a.robot_id or 0
        by_robot[rid] = by_robot.get(rid, 0) + 1

    # 点位分组 / 模板覆盖（点位维度没有告警，只能统计配置规模）
    from app.models.map_library import PlatformMap, PointDraft
    from app.models.task_template import TaskTemplate

    drafts = db.query(PointDraft).all()
    groups: dict[str, dict] = {}
    for p in drafts:
        g = p.group_name or "默认分组"
        st = groups.setdefault(g, {"group": g, "points": 0, "maps": set()})
        st["points"] += 1
        st["maps"].add(p.map_id)
    groups_out = [{"group": v["group"], "points": v["points"], "maps": len(v["maps"])}
                  for v in groups.values()]

    templates = db.query(TaskTemplate).all()
    covered: set[int] = set()
    for t in templates:
        try:
            import json as _json
            for a in _json.loads(t.actions_json or "[]"):
                if a.get("point_id"):
                    covered.add(int(a["point_id"]))
        except Exception:  # noqa: BLE001
            pass

    first_ts = db.scalar(select(func.min(TelemetrySample.ts)))
    last_ts = db.scalar(select(func.max(TelemetrySample.ts)))

    # ---- 响应与闭环：告警→确认→工单→销号，每段耗时 ----
    from app.models.inspection import WorkOrder as _WO2

    def _avg(xs: list[float]) -> float | None:
        return round(sum(xs) / len(xs), 1) if xs else None

    ack_mins: list[float] = []
    close_mins: list[float] = []
    for a in alarms:
        if a.acked_at and a.started_at:
            ack_mins.append((a.acked_at - a.started_at).total_seconds() / 60)
        if a.closed_at and a.started_at:
            close_mins.append((a.closed_at - a.started_at).total_seconds() / 60)

    alarm_ids = [a.id for a in alarms]
    orders = (db.query(_WO2)
              .filter(_WO2.created_at >= start, _WO2.created_at < end).all())
    from_alarm = [o for o in orders if o.source == "alarm" and o.source_id in alarm_ids]
    alarm_by_id = {a.id: a for a in alarms}

    alarm_to_order: list[float] = []
    order_close: list[float] = []
    for o in from_alarm:
        a = alarm_by_id.get(o.source_id)
        if a and a.started_at and o.created_at:
            alarm_to_order.append((o.created_at - a.started_at).total_seconds() / 60)
        if o.closed_at and o.created_at:
            order_close.append((o.closed_at - o.created_at).total_seconds() / 60)

    closed_orders = [o for o in orders if o.closed_at]
    on_time = [o for o in closed_orders if o.due_at and o.closed_at <= o.due_at]
    sla_on_time_rate = round(len(on_time) / len(closed_orders) * 100, 1) if closed_orders else None

    response_metrics = {
        "alarms": len(alarms),
        "alarms_acked": sum(1 for a in alarms if a.acked_at),
        "alarms_closed": sum(1 for a in alarms if a.closed_at),
        "ack_avg_min": _avg(ack_mins),
        "alarm_close_avg_min": _avg(close_mins),
        "orders": len(orders),
        "orders_from_alarm": len(from_alarm),
        "alarm_to_order_avg_min": _avg(alarm_to_order),
        "order_close_avg_min": _avg(order_close),
        "order_close_rate": round(len([o for o in from_alarm if o.closed_at]) / len(from_alarm) * 100, 1)
        if from_alarm else None,
        "sla_on_time": len(on_time),
        "sla_closed": len(closed_orders),
        "sla_on_time_rate": sla_on_time_rate,
    }

    # ---- 考核：按人/班组统计人工巡检与工单 ----
    from app.models.inspection import InspectionItem as _II
    from app.models.inspection import InspectionTask as _IT
    from app.models.inspection import WorkOrder as _WO

    users = {u.id: u.username for u in db.query(User).all()}
    perf: dict[int, dict] = {}

    def _row(uid):
        return perf.setdefault(uid, {
            "user_id": uid, "username": users.get(uid) or f"#{uid}",
            "tasks": 0, "done": 0, "overdue": 0, "items": 0, "abnormal": 0,
            "orders": 0, "closed": 0,
        })

    tasks_q = db.query(_IT).filter(_IT.created_at >= start, _IT.created_at < end).all()
    for t in tasks_q:
        if t.assignee_id is None:
            continue
        r = _row(t.assignee_id)
        r["tasks"] += 1
        if t.status == "done":
            r["done"] += 1
        elif t.due_at and t.due_at < datetime.now():
            r["overdue"] += 1
    for it in db.query(_II).filter(_II.checked_at >= start, _II.checked_at < end).all():
        t = db.get(_IT, it.task_id)
        if t is None or t.assignee_id is None:
            continue
        r = _row(t.assignee_id)
        r["items"] += 1
        if it.result == "abnormal":
            r["abnormal"] += 1
    for o in db.query(_WO).filter(_WO.created_at >= start, _WO.created_at < end).all():
        if o.assignee_id is None:
            continue
        r = _row(o.assignee_id)
        r["orders"] += 1
        if o.status == "closed":
            r["closed"] += 1

    for r in perf.values():
        r["done_rate"] = round(r["done"] / r["tasks"] * 100, 1) if r["tasks"] else None

    return {
        "response_metrics": response_metrics,
        "inspection_performance": sorted(perf.values(), key=lambda x: -x["tasks"]),
        "range": {"from": start.date().isoformat(), "to": (end - timedelta(days=1)).date().isoformat()},
        # 实际覆盖：选的区间可能没有那么多数据，页面要照实说
        "data_coverage": {
            "telemetry_from": first_ts.isoformat(timespec="minutes") if first_ts else None,
            "telemetry_to": last_ts.isoformat(timespec="minutes") if last_ts else None,
            "telemetry_days": round((last_ts - first_ts).total_seconds() / 86400, 1) if first_ts and last_ts else 0,
        },
        "alarms_by_robot": [
            {"robot_id": k, "count": v} for k, v in sorted(by_robot.items())
        ],
        "points": {
            "total": len(drafts),
            "by_group": sorted(groups_out, key=lambda x: -x["points"]),
            "covered_by_templates": len(covered),
            "uncovered": len(drafts) - len(covered),
        },
        "templates": {
            "total": len(templates),
            "actions": sum(len((_safe_actions(t))) for t in templates),
            "maps": len({t.map_id for t in templates if t.map_id}),
        },
        "alarms": {
            "total": len(alarms),
            "by_level": [{"key": k, "label": LEVELS.get(k, k), "count": v} for k, v in by_level.items()],
            "by_metric": sorted(
                [{"key": k, "count": v} for k, v in by_metric.items()],
                key=lambda x: -x["count"],
            )[:8],
            "acked": acked,
            "handled": handled,
            "closed": closed,
            "ack_rate": round(acked / len(alarms) * 100, 1) if alarms else None,
            "close_rate": round(closed / len(alarms) * 100, 1) if alarms else None,
            "avg_ack_s": _avg_seconds(ack_durations),
            "avg_close_s": _avg_seconds(close_durations),
            "by_resolution": [
                {"key": k, "label": RESOLUTIONS.get(k, k), "count": v}
                for k, v in by_resolution.items()
            ],
        },
        "environment": [
            {**v, "over_rate": round(v["over"] / v["count"] * 100, 1) if v["count"] else 0}
            for v in env_stats.values()
        ],
        "operations": {
            "samples": len(samples),
            "online_ratio": online_ratio,
            "distance_m": round(distance, 1),
            "battery_min": min(batteries) if batteries else None,
            "battery_max": max(batteries) if batteries else None,
            "battery_avg": round(sum(batteries) / len(batteries), 1) if batteries else None,
        },
    }


@router.get("/export.xlsx", dependencies=[Depends(require_roles("admin", "operator", "viewer"))])
def export_xlsx(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    """导出 Excel：概览 / 告警明细 / 环境 / 运行 四张表。"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    data = summary(date_from=date_from, date_to=date_to, db=db, user=_)
    start, end = _range(date_from, date_to)

    wb = Workbook()
    head_fill = PatternFill("solid", fgColor="005DA4")
    head_font = Font(color="FFFFFF", bold=True)

    def style_header(ws, ncols: int) -> None:
        for c in range(1, ncols + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill = head_fill
            cell.font = head_font

    ws = wb.active
    ws.title = "概览"
    ws.append(["项目", "数值"])
    rows = [
        ("统计区间", f"{data['range']['from']} ~ {data['range']['to']}"),
        ("告警总数", data["alarms"]["total"]),
        ("严重", data["alarms"]["by_level"][0]["count"]),
        ("提醒", data["alarms"]["by_level"][1]["count"]),
        ("已确认", data["alarms"]["acked"]),
        ("已处置", data["alarms"]["handled"]),
        ("已关闭", data["alarms"]["closed"]),
        ("确认率(%)", data["alarms"]["ack_rate"]),
        ("关闭率(%)", data["alarms"]["close_rate"]),
        ("平均确认时长(秒)", data["alarms"]["avg_ack_s"]),
        ("平均关闭时长(秒)", data["alarms"]["avg_close_s"]),
        ("采样点数", data["operations"]["samples"]),
        ("在线率(%)", data["operations"]["online_ratio"]),
        ("行驶里程(m)", data["operations"]["distance_m"]),
        ("电量最低(%)", data["operations"]["battery_min"]),
        ("电量最高(%)", data["operations"]["battery_max"]),
    ]
    for r in rows:
        ws.append(list(r))
    style_header(ws, 2)
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 28

    ws2 = wb.create_sheet("告警明细")
    ws2.append(["ID", "时间", "级别", "指标", "内容", "确认人", "处置人", "关闭结论", "处置说明"])
    for a in db.scalars(
        select(AlarmRecord).where(AlarmRecord.started_at >= start,
                                  AlarmRecord.started_at < end)
        .order_by(AlarmRecord.started_at)
    ).all():
        ws2.append([
            a.id,
            a.started_at.strftime("%Y-%m-%d %H:%M:%S") if a.started_at else "",
            LEVELS.get(a.level, a.level), a.metric, a.message,
            a.acked_by or "", a.handled_by or "",
            RESOLUTIONS.get(a.resolution or "", ""), a.handle_note or "",
        ])
    style_header(ws2, 9)
    for col, width in zip("ABCDEFGHI", (8, 20, 10, 22, 48, 12, 12, 14, 40)):
        ws2.column_dimensions[col].width = width

    ws3 = wb.create_sheet("环境")
    ws3.append(["传感器", "类型", "读数条数", "最小", "最大", "超限次数", "超限占比(%)", "单位"])
    for e in data["environment"]:
        ws3.append([e["name"], e["kind"], e["count"], e["min"], e["max"],
                    e["over"], e["over_rate"], e["unit"]])
    style_header(ws3, 8)
    for col, width in zip("ABCDEFGH", (22, 14, 12, 10, 10, 12, 14, 10)):
        ws3.column_dimensions[col].width = width

    # 响应与闭环（甲方最关心的"发现→处置→销号"时长）
    rm = data.get("response_metrics") or {}
    ws5 = wb.create_sheet("响应闭环")
    ws5.append(["环节", "数值"])
    for k, v in [
        ("告警总数", rm.get("alarms")),
        ("已确认", rm.get("alarms_acked")),
        ("已关闭", rm.get("alarms_closed")),
        ("平均确认时长(分钟)", rm.get("ack_avg_min")),
        ("平均关闭时长(分钟)", rm.get("alarm_close_avg_min")),
        ("转工单数", rm.get("orders_from_alarm")),
        ("告警→建单时长(分钟)", rm.get("alarm_to_order_avg_min")),
        ("工单闭环时长(分钟)", rm.get("order_close_avg_min")),
        ("工单闭环率(%)", rm.get("order_close_rate")),
    ]:
        ws5.append([k, v])
    style_header(ws5, 2)
    ws5.column_dimensions["A"].width = 26
    ws5.column_dimensions["B"].width = 16

    ws4 = wb.create_sheet("运行")
    ws4.append(["指标", "数值"])
    for k, v in [
        ("采样点数", data["operations"]["samples"]),
        ("在线率(%)", data["operations"]["online_ratio"]),
        ("里程(m)", data["operations"]["distance_m"]),
        ("电量均值(%)", data["operations"]["battery_avg"]),
        ("电量最低(%)", data["operations"]["battery_min"]),
        ("电量最高(%)", data["operations"]["battery_max"]),
    ]:
        ws4.append([k, v])
    style_header(ws4, 2)
    ws4.column_dimensions["A"].width = 20
    ws4.column_dimensions["B"].width = 20

    buf = io.BytesIO()
    wb.save(buf)

    # 中文文件名必须 RFC 5987 编码，否则 latin-1 头会直接报错
    from urllib.parse import quote

    fname = f"巡检报表_{data['range']['from']}_{data['range']['to']}.xlsx"
    ascii_name = f"report_{data['range']['from']}_{data['range']['to']}.xlsx"
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(fname)}"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": disposition},
    )
