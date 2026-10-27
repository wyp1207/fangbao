"""资源锁（最小版）：进程内锁 + DB 快照，单 worker 够用。

为什么不是 Redis/DB 行锁：
- SQLite 不支持 SELECT ... FOR UPDATE（实测语法错）；
- 单 uvicorn worker 下，进程内锁已经能保证互斥；
- DB 表只用于"重启后能看出谁占过"和页面上展示，不承担互斥职责。
ponytail: 多实例部署时必须换成 DB 条件 UPDATE 或 Redis（带 fencing token），
升级路径就是把 _LOCK 换成 DB 条件更新，接口不变。
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

_LOCK = threading.Lock()
_HELD: dict[str, dict] = {}     # key -> {run_id, robot_id, expires_at, note}


def _cleanup() -> None:
    now = time.time()
    for k, v in list(_HELD.items()):
        if v["expires_at"] < now:
            _HELD.pop(k, None)


def try_acquire(keys: list[str], *, run_id: int, robot_id: int,
                ttl_s: int = 600, note: str = "") -> bool:
    """按 key 字典序尝试抢一组锁；任一失败就回滚已拿到的（消灭环路等待）。"""
    keys = sorted(set(k for k in keys if k))
    if not keys:
        return True
    with _LOCK:
        _cleanup()
        taken: list[str] = []
        ok = True
        for k in keys:
            cur = _HELD.get(k)
            if cur and cur["run_id"] != run_id:
                ok = False
                break
            taken.append(k)
        if not ok:
            return False
        expiry = time.time() + ttl_s
        for k in keys:
            _HELD[k] = {"run_id": run_id, "robot_id": robot_id,
                        "expires_at": expiry, "note": note}
        return True


def release(keys: list[str], *, run_id: int) -> None:
    with _LOCK:
        for k in keys:
            cur = _HELD.get(k)
            if cur and cur["run_id"] == run_id:
                _HELD.pop(k, None)


def snapshot() -> list[dict]:
    """给页面/排障用：当前被占的资源（不放 DB，重启即空）。"""
    with _LOCK:
        _cleanup()
        return [{"key": k, **v} for k, v in sorted(_HELD.items())]


def persist(db, keys: list[str], *, run_id: int, robot_id: int, ttl_s: int = 600) -> None:
    """把占用写进 resource_lock 表（仅用于重启后审计/展示，失败不影响巡航）。"""
    from app.models.task_run import TaskRun  # noqa: F401  确保模型已加载
    from sqlalchemy import text

    try:
        now = datetime.now()
        for k in sorted(set(keys)):
            db.execute(text("""
                INSERT INTO resource_lock (key, run_id, robot_id, acquired_at, expires_at, note)
                VALUES (:k, :r, :rb, :a, :e, 'cruise')
                ON CONFLICT(key) DO UPDATE SET run_id=:r, robot_id=:rb,
                    acquired_at=:a, expires_at=:e
            """), {"k": k, "r": run_id, "rb": robot_id, "a": now,
                   "e": now + timedelta(seconds=ttl_s)})
        db.commit()
    except Exception:  # noqa: BLE001
        log.warning("resource_lock 落库失败（不影响互斥）", exc_info=True)
