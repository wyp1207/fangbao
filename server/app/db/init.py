"""建表与初始数据（仅 dev；生产用 Alembic）。"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import Base, SessionLocal, engine
from app.models.ai import AiAlgorithm, AiResult, ApiClient  # noqa: F401
from app.models.alarm import AlarmRecord  # noqa: F401
from app.models.inspection import InspectionItem, InspectionPlan, InspectionTask, WorkOrder  # noqa: F401
from app.models.map_library import PlatformMap, PointDraft  # noqa: F401
from app.models.message import MessageRecord  # noqa: F401
from app.models.record_plan import RecordPlan  # noqa: F401
from app.models.robot import Robot
from app.models.sensor import Sensor, SensorReading  # noqa: F401
from app.models.setting import Setting  # noqa: F401
from app.models.task_run import TaskRun, TaskRunStep  # noqa: F401
from app.models.task_template import TaskTemplate  # noqa: F401
from app.models.telemetry import TelemetrySample  # noqa: F401
from app.models.user import LoginAttempt, PasswordHistory, User  # noqa: F401
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
                must_change_password=settings.force_password_change,
            ))
            log.warning(
                "库是空的，已创建初始管理员 %s（密码取自 JC_BOOTSTRAP_PASSWORD）——"
                "首次登录后请立刻修改密码", settings.bootstrap_admin,
            )
        if db.scalar(select(Robot)) is None:
            db.add(Robot(name="JCROB-01", mode=settings.robot_mode))
            log.info("创建默认机器人记录")
        db.commit()
    seed_algorithms()


def bootstrap() -> None:
    settings = get_settings()
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.username == settings.bootstrap_admin)):
            db.add(User(
                username=settings.bootstrap_admin,
                password_hash=hash_password(settings.bootstrap_password),
                role="admin",
                must_change_password=settings.force_password_change,
            ))
            log.info("创建初始管理员 %s", settings.bootstrap_admin)
        if not db.scalar(select(Robot)):
            db.add(Robot(name="JCROB-01", mode=settings.robot_mode))
            log.info("创建默认机器人记录")
        db.commit()
    seed_algorithms()


DEFAULT_ALGORITHMS = [
    ("meter", "表计读数", "device", "MPa"),
    ("defect", "设备缺陷", "device", None),
    ("thermal", "红外测温", "device", "℃"),
    ("gas", "气体泄漏", "env", "%LEL"),
    ("smoke", "烟火识别", "env", None),
    ("helmet", "未戴安全帽", "person", None),
    ("intrusion", "区域入侵", "safety", None),
    ("fire_extinguisher", "灭火器缺失", "safety", None),
]


def seed_algorithms() -> None:
    """算法注册表：首次启动种进去，算法盒推结果时不用先手工建。"""
    with SessionLocal() as db:
        if db.scalar(select(AiAlgorithm)) is not None:
            return
        for code, name, cat, unit in DEFAULT_ALGORITHMS:
            db.add(AiAlgorithm(code=code, name=name, category=cat, unit=unit))
        db.commit()
        log.info("已写入 %d 个默认算法", len(DEFAULT_ALGORITHMS))
