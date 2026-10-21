from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Setting(Base):
    """平台运行时配置（可改、可审计、立即生效）。

    为什么不用 .env：现场调试时工程师要在页面上改阈值/保留天数，
    改完重启服务不现实。DB 里的值优先于环境变量默认值。
    """

    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, default="null")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)

    def value(self, default: Any = None) -> Any:
        try:
            return json.loads(self.value_json)
        except Exception:  # noqa: BLE001
            return default


def get_value(db, key: str, default: Any = None) -> Any:
    row = db.get(Setting, key)
    if row is None:
        return default
    return row.value(default)


def set_value(db, key: str, value: Any, *, who: str | None = None,
              note: str | None = None) -> Setting:
    row = db.get(Setting, key)
    if row is None:
        row = Setting(key=key, note=note)
        db.add(row)
    row.value_json = json.dumps(value, ensure_ascii=False)
    row.updated_at = datetime.now()
    row.updated_by = who
    row.version = (row.version or 0) + 1
    if note:
        row.note = note
    db.commit()
    db.refresh(row)
    return row
