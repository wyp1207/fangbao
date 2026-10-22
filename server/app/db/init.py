"""建表与初始数据（仅 dev；生产用 Alembic）。"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import Base, SessionLocal, engine
from app.models.alarm import AlarmRecord  # noqa: F401
from app.models.map_library import PlatformMap, PointDraft  # noqa: F401
from app.models.message import MessageRecord  # noqa: F401
from app.models.record_plan import RecordPlan  # noqa: F401
from app.models.robot import Robot
from app.models.sensor import Sensor, SensorReading  # noqa: F401
from app.models.setting import Setting  # noqa: F401
from app.models.task_template import TaskTemplate  # noqa: F401
from app.models.telemetry import TelemetrySample  # noqa: F401
from app.models.user import User
from app.models.video_source import VideoSource  # noqa: F401  create_all 需要先导入

log = logging.getLogger(__name__)


def create_all() -> None:
    Base.metadata.create_all(bind=engine)


def ensure_bootstrap() -> None:
    """生产环境也要能起：空库时建初始管理员和默认设备记录。

    和 dev 的 bootstrap 区别：这里每次都检查"表里是不是空的"，
    不是"dev 才跑"。否则全新部署后没有任何账号，连登录都进不去。
    """
    settings = get_settings()
    with SessionLocal() as db:
        if db.scalar(select(User)) is None:
            db.add(User(
                username=settings.bootstrap_admin,
                password_hash=hash_password(settings.bootstrap_password),
                role="admin",
            ))
            log.warning(
                "库是空的，已创建初始管理员 %s（密码取自 JC_BOOTSTRAP_PASSWORD）——"
                "首次登录后请立刻修改密码", settings.bootstrap_admin,
            )
        if db.scalar(select(Robot)) is None:
            db.add(Robot(name="JCROB-01", mode=settings.robot_mode))
            log.info("创建默认机器人记录")
        db.commit()


def bootstrap() -> None:
    settings = get_settings()
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.username == settings.bootstrap_admin)):
            db.add(User(
                username=settings.bootstrap_admin,
                password_hash=hash_password(settings.bootstrap_password),
                role="admin",
            ))
            log.info("创建初始管理员 %s", settings.bootstrap_admin)
        if not db.scalar(select(Robot)):
            db.add(Robot(name="JCROB-01", mode=settings.robot_mode))
            log.info("创建默认机器人记录")
        db.commit()
