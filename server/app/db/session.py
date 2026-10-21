"""数据库会话。

W1 用同步 SQLAlchemy：FastAPI 的同步依赖会跑在线程池里，不会阻塞事件循环。
换 MySQL 只改 JC_DB_URL（mysql+pymysql://user:pass@jc-mysql:3306/jcrob）。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def _engine():
    settings = get_settings()
    url = settings.db_url
    kwargs: dict = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        db_path = url.split("///", 1)[-1]
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update(pool_recycle=1800, pool_size=5, max_overflow=5)
    return create_engine(url, **kwargs)


engine = _engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
