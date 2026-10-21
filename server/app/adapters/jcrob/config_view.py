"""/system/config 白名单（唯一一份运行时实现）。

字段名取自 PDF 第 19–20 页，5.0 前后两套命名都收。
wifi_ssid / wifi_password / lagrange_id / weixin_id 故意排除：
- 前两个是凭据；
- 后两个是外部系统标识，平台用不到。

scripts/probe_jcrob.py 的 CONFIG_VIEW_FIELDS 必须与本文件一致（离线工具不 import 服务端代码）。
"""

from __future__ import annotations

from typing import Any

CONFIG_VIEW_FIELDS: frozenset[str] = frozenset({
    # 5.0 以后
    "default_map", "maps", "auto_charge", "slam_type",
    "lf_linear_v", "lf_theta_max", "lf_k2", "lf_kp", "lf_ki", "lf_kd",
    "lf_look_ahead_dist", "lf_xy_goal_tolerance", "lf_yaw_goal_tolerance",
    "lf_bar_distance_min", "lf_forward_max_dist", "lf_move_direction",
    "robot_radius", "astar_path_changeability", "go_charge_percentage",
    "use_smooth_switch_map",
    # 5.0 以前
    "navigation_speed", "max_control_speed", "bar_distance_min",
    "k2", "kp", "ki", "kd", "look_ahead_dist", "theta_max",
    "plan_width", "path_change", "forward_width", "rot_width", "backtime",
})


def project_config(payload: Any) -> dict[str, Any]:
    """只保留白名单字段；不是 dict 就返回空。"""
    if not isinstance(payload, dict):
        return {}
    return {k: v for k, v in payload.items() if k in CONFIG_VIEW_FIELDS}
