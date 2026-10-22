from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class SensorGateway(Base):
    """环境采集网关配置。

    modbus：mapping_json = [{"sensor_id": 1, "register": 40001, "scale": 0.1, "function": 3}]
    mqtt  ：topic 订阅；payload 约定 {"sensor_id": 3, "value": 12.5}
    """

    __tablename__ = "sensor_gateway"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    protocol: Mapped[str] = mapped_column(String(16), default="modbus")  # modbus/mqtt
    host: Mapped[str] = mapped_column(String(64))
    port: Mapped[int] = mapped_column(Integer, default=502)
    unit_id: Mapped[int] = mapped_column(Integer, default=1)
    topic: Mapped[str | None] = mapped_column(String(128), nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    password: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mapping_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    interval_s: Mapped[int] = mapped_column(Integer, default=10)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
