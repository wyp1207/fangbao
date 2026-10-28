"""现场自检：一条命令判断"平台/网络/设备"哪一层有问题。

给交付和运维用：不用懂代码，点一下就知道是数据库、机器人、视频还是磁盘的问题。
"""

from __future__ import annotations

import shutil
import socket
import time
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.robot import Robot
from app.models.user import User
from app.services.messages import verify_audit_chain

router = APIRouter(prefix="/system", tags=["system"])


def _tcp(host: str, port: int, timeout: float = 1.5) -> tuple[bool, str]:
    t0 = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "%dms" % int((time.time() - t0) * 1000)
    except Exception as exc:  # noqa: BLE001
        return False, "%s" % exc.__class__.__name__


def _http(url: str, timeout: float = 2.0) -> tuple[bool, str]:
    import urllib.request

    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status < 500, "HTTP %s %dms" % (r.status, int((time.time() - t0) * 1000))
    except Exception as exc:  # noqa: BLE001
        return False, "%s" % exc.__class__.__name__


@router.get("/self-check")
def self_check(db: Session = Depends(get_db),
               _: User = Depends(get_current_user)) -> dict:
    s = get_settings()
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str, hint: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail, "hint": hint})

    # 1) 数据库
    t0 = time.time()
    try:
        db.execute(text("SELECT 1"))
        add("数据库", True, "%dms" % int((time.time() - t0) * 1000))
    except Exception as exc:  # noqa: BLE001
        add("数据库", False, exc.__class__.__name__, "检查 JC_DB_URL 与数据库进程")

    # 2) 审计链（只抽查最近 500 条，避免自检太慢）
    try:
        t0 = time.time()
        chain = verify_audit_chain(db, limit=500)
        add("审计链", bool(chain.get("ok")),
            "checked=%s%s" % (chain.get("checked"),
                              "" if chain.get("ok") else "，断点 %s" % chain.get("broken_at")),
            "" if chain.get("ok") else "先备份，再用 scripts/repair_audit_chain.py 重建")
    except Exception as exc:  # noqa: BLE001
        add("审计链", False, exc.__class__.__name__)

    # 3) 设备端口
    for r in db.query(Robot).filter(Robot.is_active.is_(True)).all():
        ok, detail = _tcp(r.ip, r.port or 3546)
        add("设备 %s（%s:%s）" % (r.name, r.ip, r.port), ok, detail,
            "" if ok else "先 ping 通再查防火墙/网段；离线不等于平台故障")

    # 4) 视频网关
    base = s.go2rtc_base
    if base:
        ok, detail = _http(base.rstrip("/") + "/api/streams")
        add("视频网关 go2rtc", ok, detail, "" if ok else "检查 go2rtc 是否启动、端口是否放通")

    # 5) 磁盘
    try:
        total, used, free = shutil.disk_usage(".")
        pct = free / total * 100
        add("磁盘余量", pct > 10, "剩余 %.1f%%（%.1fGB）" % (pct, free / 1024 ** 3),
            "" if pct > 10 else "清理 data/logs、旧备份、旧录像")
    except Exception as exc:  # noqa: BLE001
        add("磁盘余量", False, exc.__class__.__name__)

    # 6) 写开关（现场下发不了任务时最常见原因）
    try:
        from app.api.v1.settings import load_all

        cfg = load_all()
        enabled = bool(cfg.get("robot.write_enabled"))
        add("写开关", True, "已开启" if enabled else "已关闭（只读演示）",
            "" if enabled else "要到 系统设置 → 下发开关 打开，或调 API")
    except Exception as exc:  # noqa: BLE001
        add("写开关", False, exc.__class__.__name__)

    ok_all = all(c["ok"] for c in checks)
    return {"ok": ok_all, "ts": datetime.now().isoformat(timespec="seconds"), "checks": checks}
