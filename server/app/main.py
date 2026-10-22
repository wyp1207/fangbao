"""应用入口。

单进程 + 进程内后台循环是刻意选择（见 docs/平台方案-定稿.md §3.1）：
状态缓存、后台循环都在进程里，不引 Redis。代价是只能 --workers 1。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.adapters.jcrob import build_adapter
from app.adapters.jcrob import errors as jerr
from app.api.v1 import (alarms, audit, auth, devices, health, map_library,
                        messages, notify, record_plans, recordings, reports, robots, sensors,
                        task_templates, telemetry,
                        settings as settings_api, users, videos)
from app.core.config import get_settings
from app.core.errors import PlatformError
from app.core.logging import setup_logging
from app.db.init import bootstrap, create_all
from app.services.alarms import AlarmStore
from app.services.state_cache import StateCache
from app.tasks.poller import StatusPoller
from app.tasks.runner import LoopLagMonitor, Service

log = logging.getLogger(__name__)


class Services:
    def __init__(self, services: list[Service], lag: LoopLagMonitor) -> None:
        self.services = services
        self.lag = lag


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    log.info("启动 %s env=%s mode=%s", settings.app_name, settings.env, settings.robot_mode)

    if settings.is_dev:
        create_all()
        bootstrap()
    else:
        # 生产库结构由 alembic 迁移负责，这里只补"空库没有账号"的兜底
        from app.db.init import ensure_bootstrap
        ensure_bootstrap()

    from app.services.robot_runtime import registry as robot_registry

    adapter = build_adapter(settings)      # 默认适配器：地图/任务等只读接口仍用它
    cache = StateCache()
    alarms = AlarmStore()
    # 告警与消息落库：重启不丢（W5 之前的最小持久化）
    from app.db.session import SessionLocal as _SessionLocal
    from app.services.messages import store as message_store

    alarms.attach_db(_SessionLocal)
    # 告警外发：入队后由后台线程发企业微信/钉钉/webhook/邮件
    from app.services import notify as notify_svc
    notify_svc.init(_SessionLocal)
    message_store.attach_db(_SessionLocal)
    robot_registry.attach_alarms(alarms)
    lag = LoopLagMonitor()

    app.state.adapter = adapter
    app.state.cache = cache
    app.state.alarms = alarms
    class _RegistryService:
        """把多设备轮询暴露成 health 里的一个服务条目（名字保持 status_poller）。"""

        name = "status_poller"

        def health(self) -> dict:
            rts = list(robot_registry.runtimes.values())
            online = sum(1 for r in rts if r.cache.as_dict()["online"])
            return {
                "name": self.name,
                "running": any(r.task is not None for r in rts),
                "robots": len(rts),
                "online": online,
                "details": [r.status() for r in rts],
            }

    app.state.services = Services([_RegistryService()], lag)

    from app.services.recorder import janitor as record_janitor

    record_janitor.start()

    from app.db.session import SessionLocal as _SL
    from app.api.v1.telemetry import TelemetryCollector, purge as telemetry_purge

    collector = TelemetryCollector(
        lambda: [(rt.robot_id, rt.cache.snapshot) for rt in robot_registry.runtimes.values()],
        _SL,
    )
    collector.start()

    from app.api.v1.record_plans import scheduler as plan_scheduler
    plan_scheduler._session_factory = _SL
    plan_scheduler.start()
    app.state.telemetry = collector

    from app.services.disk_monitor import monitor as disk_monitor
    disk_monitor.attach(alarms)
    disk_monitor.start()

    # 多设备：按台账给每台启用的设备起一个轮询任务
    from app.db.session import SessionLocal as _SL2
    from app.models.robot import Robot as _Robot

    with _SL2() as _db:
        _robots = _db.query(_Robot).filter(_Robot.is_active.is_(True)).all()
    await robot_registry.start(_robots)
    lag.start()
    try:
        yield
    finally:
        # 录像进程是外部 ffmpeg，必须显式收掉，否则会变成孤儿进程
        from app.services.recorder import registry as recorder_registry
        recorder_registry.stop_all()
        try:
            from app.services.disk_monitor import monitor as disk_monitor
            disk_monitor.stop()
        except Exception:  # noqa: BLE001
            pass
        record_janitor.stop()
        try:
            plan_scheduler.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            app.state.telemetry.stop()
        except Exception:  # noqa: BLE001
            pass
        await robot_registry.stop()
        await lag.stop()
        await adapter.aclose()
        log.info("已停止")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(PlatformError)
    async def _platform_error(_: Request, exc: PlatformError):
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(jerr.JcrobError)
    async def _jcrob_error(_: Request, exc: jerr.JcrobError):
        return JSONResponse(
            status_code=exc.http_status,
            content={"code": exc.code, "message": exc.message, "details": exc.details},
        )

    app.include_router(health.router)
    app.include_router(auth.router, prefix=settings.api_prefix)
    app.include_router(robots.router, prefix=settings.api_prefix)
    app.include_router(alarms.router, prefix=settings.api_prefix)
    app.include_router(users.router, prefix=settings.api_prefix)
    app.include_router(videos.router, prefix=settings.api_prefix)
    app.include_router(recordings.router, prefix=settings.api_prefix)
    app.include_router(record_plans.router, prefix=settings.api_prefix)
    app.include_router(messages.router, prefix=settings.api_prefix)
    app.include_router(audit.router, prefix=settings.api_prefix)
    app.include_router(devices.router, prefix=settings.api_prefix)
    app.include_router(map_library.router, prefix=settings.api_prefix)
    app.include_router(settings_api.router, prefix=settings.api_prefix)
    app.include_router(sensors.router, prefix=settings.api_prefix)
    app.include_router(notify.router, prefix=settings.api_prefix)
    app.include_router(reports.router, prefix=settings.api_prefix)
    app.include_router(task_templates.router, prefix=settings.api_prefix)
    app.include_router(telemetry.router, prefix=settings.api_prefix)
    return app


app = create_app()
