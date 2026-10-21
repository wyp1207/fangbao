"""角度与单位归一化。

事实（PDF）：
- /navigation/pose.angle、/map/pose.angle 单位是**度**（p59、p54）；
- nav_action.theta、local_move.angle 单位是**弧度**（p91）；
- /system/galileo_status.currentAngle 原文没标（p11 只写 // map z (yaw)）；
- nav_points 的 theta 原文没标，样例值域在 ±π 内。

平台内部统一存弧度；判定不出就保持 "unknown"，页面显示“角度单位待确认”。
"""

from __future__ import annotations

import math
from statistics import mean
from typing import Iterable, Literal, Sequence

AngleUnit = Literal["deg", "rad", "unknown"]


def deg_to_rad(value: float) -> float:
    return math.radians(value)


def rad_to_deg(value: float) -> float:
    return math.degrees(value)


def wrap_pi(rad: float) -> float:
    """归一到 (-pi, pi]，用于比较两个朝向。"""
    return (rad + math.pi) % (2.0 * math.pi) - math.pi


def circular_error(a: float, b: float) -> float:
    """两个弧度值的圆周误差，恒 >= 0。"""
    return abs(wrap_pi(a - b))


def resolve_angle_unit(
    pairs: Sequence[tuple[float, float]],
    *,
    min_samples: int = 3,
    max_acceptable_deg: float = 15.0,
    min_ratio: float = 2.0,
    min_discrimination_deg: float = 2.0,
) -> dict:
    """多帧判定 currentAngle 是度还是弧度。

    pairs: [(currentAngle 原始值, pose.angle 度值), ...]
    不靠单帧比值：角度接近 0 时两者都接近 0，比值无意义；
    也不直接比数值：yaw 过 ±180/±π 会被环绕破坏。
    """
    usable = [
        (float(ga), float(pa)) for ga, pa in pairs
        if isinstance(ga, (int, float)) and isinstance(pa, (int, float))
        and not isinstance(ga, bool) and not isinstance(pa, bool)
    ]
    result: dict = {
        "samples": len(usable),
        "mean_abs_err_if_deg": None,
        "mean_abs_err_if_rad": None,
        "pose_spread_deg": None,
        "verdict": "unknown",
        "reason": "",
    }
    if len(usable) < min_samples:
        result["reason"] = "可用样本不足"
        return result

    err_deg = mean(circular_error(deg_to_rad(ga), deg_to_rad(pa)) for ga, pa in usable)
    err_rad = mean(circular_error(ga, deg_to_rad(pa)) for ga, pa in usable)
    ref = usable[0][1]
    spread = max(abs(wrap_pi(deg_to_rad(pa - ref))) for _, pa in usable)

    result.update(
        mean_abs_err_if_deg=round(rad_to_deg(err_deg), 3),
        mean_abs_err_if_rad=round(rad_to_deg(err_rad), 3),
        pose_spread_deg=round(rad_to_deg(spread), 2),
    )

    best, worst = min(err_deg, err_rad), max(err_deg, err_rad)
    # 两种假设对同一原始值给出的角度差多少：差得太小就没有判别力
    # （例如机器人静止且朝向≈0 时，度和弧度的数值几乎相同）
    discrimination = mean(abs(wrap_pi(deg_to_rad(ga) - ga)) for ga, _ in usable)
    result["discrimination_deg"] = round(rad_to_deg(discrimination), 3)

    if discrimination < math.radians(min_discrimination_deg):
        result["reason"] = "两种假设预测角几乎相同（机器人静止且朝向接近 0），判不了"
    elif best > math.radians(max_acceptable_deg):
        result["reason"] = "两种假设误差都过大：可能不是同一时刻或未初始化"
    elif worst < best * min_ratio:
        result["reason"] = "两种假设差距不足，判不了；换一段机器人明显转向的采样"
    else:
        result["verdict"] = "deg" if err_deg < err_rad else "rad"
        result["reason"] = "圆周误差更小的一侧胜出"
    return result


def normalize_angle(value: float | None, unit: AngleUnit) -> float | None:
    """把任意来源的角度转成平台内部弧度；单位未知时返回 None（不猜）。"""
    if value is None:
        return None
    if unit == "deg":
        return deg_to_rad(value)
    if unit == "rad":
        return wrap_pi(value)
    return None


def theta_from_nav_points(raw: float | None) -> float | None:
    """nav_points.theta：读按弧度（PDF 样例值域 ±π）；写回前必须实测确认。"""
    if raw is None:
        return None
    return wrap_pi(float(raw))


def parse_nav_points_line(line: str) -> dict | None:
    """解析 nav_points 的 path_data 单行。

    PDF p72 说明是 8 字段 x y z theta errorX errorY direction name，
    但样例每行只有 7 个（name 为空被省略）。
    用 maxsplit=7：前 7 个固定，剩余全部归 name（名字里带空格不会断）。
    """
    parts = line.strip().split(maxsplit=7)
    if len(parts) < 7:
        return None
    try:
        return {
            "x": float(parts[0]),
            "y": float(parts[1]),
            "z": float(parts[2]),
            "theta_rad": wrap_pi(float(parts[3])),
            "error_x": float(parts[4]),
            "error_y": float(parts[5]),
            "direction": parts[6],
            "name": parts[7].strip() if len(parts) > 7 else "",
        }
    except ValueError:
        return None


def dump_nav_point(point: dict) -> str:
    """写回一行：name 为空时输出 7 字段，不带尾随空格。"""
    head = " ".join([
        f"{point['x']:g}", f"{point['y']:g}", f"{point.get('z', 0):g}",
        f"{point['theta_rad']:.6f}",
        f"{point.get('error_x', 0.1):g}", f"{point.get('error_y', 0.1):g}",
        str(point.get("direction", "0")),
    ])
    name = point.get("name") or ""
    return f"{head} {name}".rstrip()


def parse_nav_points(path_data: str) -> list[dict]:
    rows: list[dict] = []
    for line in (path_data or "").splitlines():
        if not line.strip():
            continue
        parsed = parse_nav_points_line(line)
        if parsed:
            rows.append(parsed)
    return rows


def dump_nav_points(points: Iterable[dict]) -> str:
    return "\n".join(dump_nav_point(p) for p in points)
