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
from app.api.v1 import alarms, auth, health, robots, users, videos
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

    adapter = build_adapter(settings)
    cache = StateCache()
    alarms = AlarmStore()
    poller = StatusPoller(adapter, cache, settings.jcrob_poll_interval, alarms=alarms)
    poller_service = Service("status_poller", poller)
    lag = LoopLagMonitor()

    app.state.adapter = adapter
    app.state.cache = cache
    app.state.alarms = alarms
    app.state.services = Services([poller_service], lag)

    poller_service.start()
    lag.start()
    try:
        yield
    finally:
        await poller_service.stop()
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
    return app


app = create_app()
