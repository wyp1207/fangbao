"""Adapter 工厂：只在这里决定用真机还是 Mock。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.adapters.jcrob.http_adapter import HttpJcrobAdapter
from app.adapters.jcrob.mock_adapter import MockJcrobAdapter

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config import Settings
    from app.models.robot import Robot


def build_adapter(settings: "Settings", robot: "Robot | None" = None):
    mode = (robot.mode if robot else None) or settings.robot_mode
    angle_unit = (robot.angle_unit_override if robot else None) or "auto"
    if mode == "http":
        base_url = settings.jcrob_base_url
        port = robot.port if robot else None
        if robot and port and f":{port}" not in base_url:
            scheme, _, rest = base_url.partition("://")
            host = rest.split(":")[0].split("/")[0]
            base_url = f"{scheme}://{host}:{port}"
        return HttpJcrobAdapter(
            base_url=base_url,
            username=settings.jcrob_username,
            password=settings.jcrob_password,
            token=settings.jcrob_token,
            timeout=settings.jcrob_http_timeout,
            angle_unit=angle_unit,  # type: ignore[arg-type]
        )
    return MockJcrobAdapter(settings.jcrob_fixtures, angle_unit=angle_unit)


__all__ = ["build_adapter", "HttpJcrobAdapter", "MockJcrobAdapter"]
