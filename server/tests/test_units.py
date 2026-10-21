from app.adapters.jcrob.units import (
    dump_nav_point,
    parse_nav_points,
    parse_nav_points_line,
    resolve_angle_unit,
    wrap_pi,
)


def test_parse_seven_fields_name_empty():
    p = parse_nav_points_line("-4 0 0 1.570796 0.1 0.1 0")
    assert p["x"] == -4.0
    assert abs(p["theta_rad"] - 1.570796) < 1e-6
    assert p["name"] == ""


def test_parse_eight_fields_with_space_in_name():
    p = parse_nav_points_line("1 2 0 0.5 0.1 0.1 0 一号门 东侧")
    assert p["name"] == "一号门 东侧"
    assert abs(p["theta_rad"] - 0.5) < 1e-9


def test_roundtrip_drops_trailing_space():
    line = dump_nav_point({"x": 1, "y": 2, "theta_rad": 0.5, "name": ""})
    assert line == "1 2 0 0.500000 0.1 0.1 0"
    assert not line.endswith(" ")


def test_parse_rejects_short_line():
    assert parse_nav_points_line("1 2 3") is None


def test_parse_multi_line():
    rows = parse_nav_points("-4 0 0 0 0.1 0.1 0\n1 2 0 0.5 0.1 0.1 0\n")
    assert len(rows) == 2


def test_wrap_pi():
    assert abs(wrap_pi(3.5) - (3.5 - 6.283185307179586)) < 1e-9


def test_angle_unit_deg():
    pairs = [(90.0 + i * 20, 90.0 + i * 20) for i in range(5)]
    result = resolve_angle_unit(pairs)
    assert result["verdict"] == "deg"


def test_angle_unit_rad():
    import math

    pairs = [(math.radians(90 + i * 20), 90.0 + i * 20) for i in range(5)]
    result = resolve_angle_unit(pairs)
    assert result["verdict"] == "rad"


def test_angle_unit_unknown_when_static_at_zero():
    pairs = [(0.0, 0.0) for _ in range(5)]
    result = resolve_angle_unit(pairs)
    assert result["verdict"] == "unknown"


def test_angle_unit_not_enough_samples():
    result = resolve_angle_unit([(90.0, 90.0)])
    assert result["verdict"] == "unknown"
    assert "样本" in result["reason"]
