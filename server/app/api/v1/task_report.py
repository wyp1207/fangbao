"""任务级巡检报告（xlsx）。

一张表说清：任务信息、每个点位结果、期间告警。
不嵌入照片二进制（会让文件从几十 KB 变成几十 MB），照片按点位列文件名/链接。
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.errors import NotFound
from app.db.session import get_db
from app.models.alarm import AlarmRecord
from app.models.robot import Robot
from app.models.task_run import TaskRun, TaskRunStep
from app.models.user import User

router = APIRouter(tags=["task-report"])

STATUS_TEXT = {"planned": "计划中", "running": "执行中", "done": "已完成",
               "failed": "失败", "cancelled": "已取消"}
STEP_TEXT = {"pending": "未执行", "ok": "正常", "failed": "异常", "skipped": "跳过"}


@router.get("/task-runs/{run_id}/report.xlsx")
def run_report(
    run_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "operator", "safety", "viewer")),
) -> StreamingResponse:
    run = db.get(TaskRun, run_id)
    if run is None:
        raise NotFound("任务不存在")
    steps = (db.query(TaskRunStep).filter(TaskRunStep.run_id == run_id)
             .order_by(TaskRunStep.seq).all())
    robot = db.get(Robot, run.robot_id) if run.robot_id else None

    start = run.started_at or run.created_at
    end = run.finished_at or datetime.now()
    alarms = (db.query(AlarmRecord)
              .filter(AlarmRecord.started_at >= start - timedelta(minutes=5),
                      AlarmRecord.started_at <= end + timedelta(minutes=5))
              .order_by(AlarmRecord.started_at).all())

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "巡检报告"

    head_fill = PatternFill("solid", fgColor="0B4A7A")
    head_font = Font(color="FFFFFF", bold=True, size=11)
    thin = Side(style="thin", color="B8D4E8")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def put(row: int, col: int, value, bold: bool = False, fill=None):
        cell = ws.cell(row=row, column=col, value=value)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = border
        if bold:
            cell.font = Font(bold=True)
        if fill:
            cell.fill = fill
        return cell

    ws.merge_cells("A1:F1")
    ws["A1"] = f"巡检报告 · {run.name}"
    ws["A1"].font = Font(size=16, bold=True, color="0B3A5A")
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 30

    info = [
        ("任务编号", f"#{run.id}", "任务状态", STATUS_TEXT.get(run.status, run.status)),
        ("执行设备", robot.name if robot else "—", "任务模板", str(run.template_id or "—")),
        ("开始时间", start.strftime("%Y-%m-%d %H:%M:%S"), "结束时间",
         run.finished_at.strftime("%Y-%m-%d %H:%M:%S") if run.finished_at else "—"),
        ("点位总数", len(steps), "成功/失败",
         f"{sum(1 for s in steps if s.status == 'ok')}/{sum(1 for s in steps if s.status == 'failed')}"),
        ("报告生成", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "数据来源", "平台运行记录"),
    ]
    row = 3
    for k1, v1, k2, v2 in info:
        put(row, 1, k1, bold=True, fill=head_fill).font = head_font
        put(row, 2, v1)
        put(row, 3, k2, bold=True, fill=head_fill).font = head_font
        put(row, 4, v2)
        row += 1

    row += 1
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
    put(row, 1, "点位执行结果", bold=True, fill=head_fill).font = head_font
    row += 1
    headers = ["序号", "点位", "动作", "状态", "耗时(秒)", "备注"]
    for i, h in enumerate(headers, 1):
        c = put(row, i, h, bold=True, fill=head_fill)
        c.font = head_font
    row += 1
    for s in steps:
        dur = None
        if s.started_at and s.finished_at:
            dur = round((s.finished_at - s.started_at).total_seconds(), 1)
        put(row, 1, s.seq)
        put(row, 2, s.point_name or "—")
        put(row, 3, s.action)
        put(row, 4, STEP_TEXT.get(s.status, s.status))
        put(row, 5, dur if dur is not None else "—")
        put(row, 6, s.error or "")
        if s.status == "failed":
            ws.cell(row=row, column=4).font = Font(color="C00000", bold=True)
        row += 1
    if not steps:
        put(row, 1, "（无点位记录）")
        row += 1

    row += 1
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
    put(row, 1, "任务期间告警", bold=True, fill=head_fill).font = head_font
    row += 1
    for i, h in enumerate(["时间", "级别", "内容", "确认状态", "", ""], 1):
        c = put(row, i, h, bold=True, fill=head_fill)
        c.font = head_font
    row += 1
    for a in alarms:
        put(row, 1, a.started_at.strftime("%m-%d %H:%M:%S"))
        put(row, 2, "严重" if a.level == "critical" else "注意")
        put(row, 3, a.message)
        put(row, 4, "已确认" if a.acked_at else "未确认")
        row += 1
    if not alarms:
        put(row, 1, "（期间无告警）")
        row += 1

    widths = [10, 22, 12, 12, 12, 40]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A5"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"inspection-report-{run.id}-{datetime.now().strftime('%Y%m%d%H%M')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )
