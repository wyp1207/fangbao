"""设备适配器注册表：一台设备 = 一个适配器实例。

为什么要这层：不同本体（JCROB 轮式 / 宇树 G1 人形 / 云深处 X30 四足）
的协议、坐标系、任务模型都不一样。平台只认统一的数据结构，
差异全部收敛在适配器里。

**没实现的适配器要明确报"不支持"，而不是假装能连。**
UI 上显示"待接入：缺 SDK 文档"才是诚实的做法。
"""

from __future__ import annotations

from typing import Any

from app.adapters.jcrob import HttpJcrobAdapter, MockJcrobAdapter


class AdapterNotSupported(Exception):
    """这个 device_type 还没有可用适配器。"""

    def __init__(self, adapter: str, reason: str) -> None:
        super().__init__(reason)
        self.adapter = adapter
        self.reason = reason


# 已知协议 → 说明（用于 UI 展示"为什么还不能用"）
ADAPTERS: dict[str, dict[str, Any]] = {
    "jcrob_http": {
        "label": "JCROB HTTP",
        "device_type": "jcrob_wheel",
        "supported": True,
        "needs": [],
        "note": "轮式防爆机器人，HTTP 3546 + WS 3547",
    },
    "jcrob_mock": {
        "label": "模拟设备",
        "device_type": "mock",
        "supported": True,
        "needs": [],
        "note": "不连真机，用契约样例数据",
    },
    "unitree_sdk": {
        "label": "宇树 G1（SDK2/DDS）",
        "device_type": "unitree_g1",
        "supported": False,
        "needs": ["Unitree SDK2 文档与版本", "DDS 网络可达", "一台可连的 G1 样机"],
        "note": "人形机器人，导航/任务模型与 JCROB 不同，适配器待开发",
    },
    "deeprobotics_x30": {
        "label": "云深处 X30（本体监控 TCP 30000）",
        "device_type": "deeprobotics_x30",
        "supported": True,
        "needs": [],
        "note": "实测：帧头 EB90EB90，状态/电池/任务状态可读；导航与起立趴下走同一通道",
    },
    "other_http": {
        "label": "其他（HTTP 只读）",
        "device_type": "other",
        "supported": False,
        "needs": ["该设备的接口文档", "状态字段映射表"],
        "note": "只登记台账，暂不通信",
    },
}

DEVICE_TYPES = [
    {"value": "jcrob_wheel", "label": "轮式防爆巡检机器人（JCROB）"},
    {"value": "unitree_g1", "label": "宇树 G1 人形机器人"},
    {"value": "deeprobotics_x30", "label": "云深处 X30 四足机器狗"},
    {"value": "other", "label": "其他设备"},
]


def build_for(robot, *, settings, cache=None):
    """按设备的 adapter 字段造适配器。

    返回 (adapter, error)：error 非空表示这台设备暂时不能通信。
    """
    # 设备台账的 mode=mock 优先：开发/演示环境不连真机，
    # 即使 adapter 写的是 jcrob_http 也不该去打 192.168.1.100
    if (getattr(robot, "mode", "") or "") == "mock":
        return MockJcrobAdapter(settings.jcrob_fixtures), None

    adapter_key = (robot.adapter or "").strip() or "jcrob_http"
    meta = ADAPTERS.get(adapter_key)

    if meta is None:
        raise AdapterNotSupported(adapter_key, f"未知适配器 {adapter_key}")

    if adapter_key == "jcrob_mock":
        return MockJcrobAdapter(settings.jcrob_fixtures), None

    if adapter_key == "deeprobotics_x30":
        from app.adapters.deeprobotics import DeepRoboticsX30Adapter

        host = (robot.ip or settings.x30_host or "192.168.1.106").strip()
        port = int(robot.port or settings.x30_port or 30000)
        return DeepRoboticsX30Adapter(host, port, timeout=settings.x30_timeout), None

    if adapter_key == "jcrob_http":
        from app.core.security import unseal

        base_url = f"http://{robot.ip}:{robot.port}"
        password = unseal(robot.password_cipher or "", secret=settings.secret_key) \
            or settings.jcrob_password
        return HttpJcrobAdapter(
            base_url=base_url,
            username=robot.username or settings.jcrob_username,
            password=password,
            token=settings.jcrob_token,
            timeout=settings.jcrob_http_timeout,
            angle_unit=robot.angle_unit_override or "auto",  # type: ignore[arg-type]
        ), None

    # 未实现的协议：明确告知缺什么，不返回半成品适配器
    raise AdapterNotSupported(
        adapter_key,
        f"{meta['label']} 适配器未实现，需要：{'、'.join(meta['needs'])}",
    )
