"""应用入口。

单进程 + 进程内后台循环是刻意选择（见 docs/平台方案-定稿.md §3.1）：
状态缓存、后台循环都在进程里，不引 Redis。代价是只能 --workers 1。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from starlette.middleware.base import BaseHTTPMiddleware

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.adapters.jcrob import build_adapter
from app.adapters.jcrob import errors as jerr
import app.models.peripheral  # noqa: F401  确保建表/迁移能看到
import app.models.device_credential  # noqa: F401  设备接入凭证
from app.api.v1 import (alarms, audit, auth, device_keys, devices, feed, health, map_library,
                        self_check, metrics as health_metrics, peripherals,
                        ai, api_clients, inspection, messages, notify, sensor_gateways, record_plans, recordings, reports, robots, sensors,
                        task_runs, task_templates, telemetry,
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
    from app.core.config import assert_production_safe
    assert_production_safe()
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
    # 服务重启后，上次残留的 running 任务状态已不可知：标成 failed 并写明原因，
    # 不要让它一直显示"执行中"（评审共识：宁可显示未知，也不要撒谎）
    try:
        from app.models.task_run import TaskRun as _TR
        with _SL() as _db:
            stale = _db.query(_TR).filter(_TR.status.in_(("running", "dispatched"))).all()
            for r in stale:
                r.status = "failed"
                r.dispatch_error = "服务重启，任务状态未知；请确认机器人是否仍在执行"
            if stale:
                _db.commit()
                import logging as _lg
                _lg.getLogger(__name__).warning("标记 %s 条重启前残留任务为 failed", len(stale))
    except Exception:  # noqa: BLE001
        pass

    # 预热报表缓存：避免首个打开报表的人触发 2.4s 冷查询
    def warm_summary() -> None:
        import time as _t

        if settings.env == "test":
            return
        _t.sleep(5)
        try:
            from app.api.v1 import reports as _reports

            with _SL() as _db:
                _reports._summary_impl(date_from=None, date_to=None, db=_db, user=None)  # noqa: SLF001
            _reports._SUMMARY_CACHE[(None, None)] = (_t.time(), _reports._summary_impl(
                date_from=None, date_to=None, db=_SL(), user=None))  # noqa: SLF001
        except Exception:  # noqa: BLE001
            pass

    import threading as _th
    _th.Thread(target=warm_summary, daemon=True, name="warm-summary").start()

    robot_registry.attach_alarms(alarms)
    from app.services.alarms import bind_store
    bind_store(alarms)
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
    from app.api.v1.telemetry import TelemetryCollector, purge as telemetry_purge, rollup as telemetry_rollup

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

    # 遥测/环境读数保留期清理（原来 purge() 只定义没调度，表会无限长）
    def _telemetry_janitor():
        import time as _t
        while True:
            try:
                from app.api.v1.settings import load_all
                cfg = load_all()
                try:
                    n = telemetry_rollup(_SL, hours=26)
                    if n:
                        log.info("遥测聚合：写入 %s 个分钟桶", n)
                except Exception:  # noqa: BLE001
                    pass
                telemetry_purge(_SL, keep_days=int(cfg.get("telemetry.keep_days", 7)))
                # 环境读数单独保留期：10 测点 5s 采样一年 6300 万行，不清会先 OOM 再爆盘
                try:
                    from datetime import datetime as _dt, timedelta as _td

                    from app.models.sensor import SensorReading

                    cutoff = _dt.now() - _td(days=int(cfg.get("sensor.keep_days", 90)))
                    with _SL() as _db:
                        _db.query(SensorReading).filter(SensorReading.ts < cutoff).delete(
                            synchronize_session=False)
                        _db.commit()
                except Exception:  # noqa: BLE001
                    pass
            except Exception:  # noqa: BLE001
                pass
            _t.sleep(6 * 3600)

    import threading as _th
    telemetry_janitor = _th.Thread(target=_telemetry_janitor, daemon=True)
    telemetry_janitor.start()

    # 搁置到期恢复：单独一个 60 秒的轻量循环（保留期清理是 6 小时一次，太粗）
    def _backup_janitor():
        """每天 02:00 自动备份一次库（沿用 scripts/backup_db.py 的 sqlite backup API）。"""
        import time as _t
        from datetime import datetime as _dt

        while True:
            now = _dt.now()
            wait = ((2 - now.hour) % 24) * 3600 + (0 - now.minute) * 60 - now.second
            _t.sleep(max(60, wait))
            try:
                import sqlite3
                from pathlib import Path

                from app.core.config import get_settings as _gs

                src = Path(str(_gs().db_url).split("///")[-1])
                if not src.is_absolute():
                    src = Path(__file__).resolve().parents[2] / src
                out_dir = src.parent / "backups"
                out_dir.mkdir(parents=True, exist_ok=True)
                dst = out_dir / ("auto-%s.db" % _dt.now().strftime("%Y%m%d"))
                with sqlite3.connect(src) as sdb, sqlite3.connect(dst) as ddb:
                    sdb.backup(ddb)
                # 只留最近 14 天
                olds = sorted(out_dir.glob("auto-*.db"))[:-14]
                for old in olds:
                    old.unlink()
                log.info("每日备份完成：%s", dst.name)
            except Exception:  # noqa: BLE001
                log.exception("每日备份失败")

    _bk = _th.Thread(target=_backup_janitor, daemon=True)
    _bk.start()

    def _dispatch_janitor():
        import time as _t
        from app.services.device_auth import purge_nonces
        from app.services.task_dispatch import reconcile_dispatches
        while True:
            try:
                with _SL() as db:
                    reconcile_dispatches(db)
                    purge_nonces(db)
            except Exception:  # noqa: BLE001
                log.exception("下发对账失败")
            _t.sleep(60)

    dispatch_janitor = _th.Thread(target=_dispatch_janitor, daemon=True)
    dispatch_janitor.start()

    def _shelve_janitor():
        import time as _t
        from app.services.alarms import clear_expired_shelves
        while True:
            try:
                n = clear_expired_shelves(_SL)
                if n:
                    log.info("搁置到期自动恢复 %s 条告警", n)
            except Exception:  # noqa: BLE001
                log.exception("搁置到期清理失败")
            _t.sleep(60)

    shelve_janitor = _th.Thread(target=_shelve_janitor, daemon=True)
    shelve_janitor.start()

    from app.services import cruise as cruise_module
    cruise_module.runner = cruise_module.CruiseRunner(_SL)

    from app.services import sensor_gateway as sg_module
    sg_module.runner = sg_module.SensorGatewayRunner(_SL)
    try:
        sg_module.runner.start_all()
    except Exception:  # noqa: BLE001
        pass

    from app.services.task_dispatch import TaskWatchdog
    task_watchdog = TaskWatchdog(_SL)
    task_watchdog.start()

    from app.services.work_orders import WorkOrderEscalator
    wo_escalator = WorkOrderEscalator(_SL)
    wo_escalator.start()
    disk_monitor.start()

    # 多设备：按台账给每台启用的设备起一个轮询任务
    from app.db.session import SessionLocal as _SL2
    from app.models.robot import Robot as _Robot

    with _SL2() as _db:
        _robots = _db.query(_Robot).filter(_Robot.is_active.is_(True)).all()
    from app.services.async_bridge import set_loop

    set_loop(asyncio.get_running_loop())

    await robot_registry.start(_robots)

    # 环境传感器走机器人推的 WS（SDK p107），与 HTTP 轮询是两套机制
    try:
        from app.services.env_ws import runner as env_ws_runner

        await env_ws_runner.start(_robots)
    except Exception:  # noqa: BLE001
        log.exception("环境流启动失败（不影响主流程）")

    lag.start()
    try:
        yield
    finally:
        # 录像进程是外部 ffmpeg，必须显式收掉，否则会变成孤儿进程
        from app.services.recorder import registry as recorder_registry
        recorder_registry.stop_all()
        try:
            sg_module.runner.stop_all()
        except Exception:  # noqa: BLE001
            pass
        try:
            task_watchdog.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            wo_escalator.stop()
        except Exception:  # noqa: BLE001
            pass
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
        try:
            from app.services.env_ws import runner as env_ws_runner

            await env_ws_runner.stop()
        except Exception:  # noqa: BLE001
            pass
        await lag.stop()
        await adapter.aclose()
        log.info("已停止")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """每个请求一个 request_id；访问日志一行一条，排障时按 id 串。"""

    async def dispatch(self, request, call_next):
        import time as _t
        import uuid as _uuid

        rid = request.headers.get("X-Request-Id") or _uuid.uuid4().hex[:12]
        request.state.request_id = rid
        t0 = _t.time()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("请求异常 rid=%s %s %s", rid, request.method, request.url.path)
            raise
        cost = int((_t.time() - t0) * 1000)
        if cost >= 800:
            log.warning("慢请求 rid=%s %s %s -> %s %sms", rid, request.method,
                        request.url.path, response.status_code, cost)
        else:
            log.info("rid=%s %s %s -> %s %sms", rid, request.method, request.url.path,
                     response.status_code, cost)
        response.headers["X-Request-Id"] = rid
        return response


def create_app() -> FastAPI:
    settings = get_settings()
    _docs = bool(get_settings().docs_enabled)
    app = FastAPI(
        docs_url="/docs" if _docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if _docs else None,
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def _metrics_mw(request: Request, call_next):
        """记请求量/耗时/5xx，供 /metrics 抓取。"""
        import time as _t

        t0 = _t.perf_counter()
        try:
            resp = await call_next(request)
        except Exception:
            health_metrics.record(request.method, request.url.path, 500, _t.perf_counter() - t0)
            raise
        health_metrics.record(request.method, request.url.path, resp.status_code, _t.perf_counter() - t0)
        return resp

    app.add_middleware(RequestContextMiddleware)

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
    app.include_router(feed.router, prefix=settings.api_prefix)
    app.include_router(peripherals.router, prefix=settings.api_prefix)
    app.include_router(health_metrics.router)
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
    app.include_router(device_keys.router, prefix=settings.api_prefix)
    app.include_router(self_check.router, prefix=settings.api_prefix)
    app.include_router(settings_api.router, prefix=settings.api_prefix)
    app.include_router(sensors.router, prefix=settings.api_prefix)
    app.include_router(notify.router, prefix=settings.api_prefix)
    app.include_router(reports.router, prefix=settings.api_prefix)
    app.include_router(task_templates.router, prefix=settings.api_prefix)
    app.include_router(task_runs.router, prefix=settings.api_prefix)
    app.include_router(inspection.router, prefix=settings.api_prefix)
    app.include_router(ai.router, prefix=settings.api_prefix)
    app.include_router(api_clients.router, prefix=settings.api_prefix)
    app.include_router(sensor_gateways.router, prefix=settings.api_prefix)
    app.include_router(telemetry.router, prefix=settings.api_prefix)
    return app


app = create_app()
