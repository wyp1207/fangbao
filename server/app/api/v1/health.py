from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from app.api.deps import get_cache, get_current_user, get_services
from app.core.config import get_settings

router = APIRouter(tags=["health"])


def _disk_snapshot() -> dict:
    try:
        from app.services.disk_monitor import snapshot
        return snapshot()
    except Exception:  # noqa: BLE001
        return {}
_started = time.monotonic()


@router.get("/health")
def health() -> dict:
    """存活探针：不查库、不查机器人，给 docker/nginx 用。"""
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.env,
        "robot_mode": settings.robot_mode,
        "uptime_s": round(time.monotonic() - _started, 1),
    }


@router.get("/ready")
def ready() -> dict:
    """就绪探针：真的查一次库。容器活着但库断了，/health 发现不了。"""
    from sqlalchemy import text

    from app.db.session import SessionLocal

    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as exc:  # noqa: BLE001
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=503,
                            content={"status": "not_ready", "error": exc.__class__.__name__})


@router.get("/api/v1/health/deep")
def health_deep(cache=Depends(get_cache), services=Depends(get_services),
                _user=Depends(get_current_user)) -> dict:
    """深探针：链路是否在线、后台循环是否活着、事件循环有没有卡。

    注意 online 是“平台到机器人”的链路状态，不是 /system/is_online（那是机器人能不能上互联网）。
    """
    from app.services.robot_runtime import registry as robot_registry

    default_rt = robot_registry.default()
    snap = (default_rt.cache if default_rt is not None else cache).as_dict()
    return {
        "cache": {
            "online": snap["online"],
            "age_s": snap["age_s"],
            "consecutive_failures": snap["consecutive_failures"],
            "last_error": snap["last_error"],
            "poll_count": snap["poll_count"],
        },
        "services": [svc.health() for svc in services.services],
        "loop_lag_ms": services.lag.lag_ms,
        "disks": _disk_snapshot(),
    }
