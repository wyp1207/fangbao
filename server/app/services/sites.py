"""场站（site）的公共逻辑：code 生成、默认站、归属校验。

放在 service 层的原因：模板创建/更新、下发校验、迁移外的运维脚本都要用同一套
规则，散在 API 里会各写一份，最后又是"两个地方判断不一致"。
"""

from __future__ import annotations

import hashlib
import re

from sqlalchemy.orm import Session

from app.core.errors import BadRequest, NotFound, PlatformError
from app.models.map_library import PlatformMap
from app.models.robot import Robot
from app.models.site import Site

DEFAULT_STATION = "默认场站"


def slugify(name: str) -> str:
    text = (name or "").strip()
    if text == DEFAULT_STATION:
        return "default"
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:64]


def code_for(name: str) -> str:
    """ASCII 名走 slug；中文走稳定短 hash（同一名字永远得到同一 code）。"""
    slug = slugify(name)
    if slug:
        return slug
    return "site-" + hashlib.sha1((name or "").strip().encode("utf-8")).hexdigest()[:10]


def unique_code(db: Session, name: str, explicit: str | None = None) -> str:
    if explicit:
        code = explicit.strip()
        if not code:
            raise BadRequest("code 不能为空", code="BAD_SITE_CODE")
        if db.query(Site).filter(Site.code == code).first():
            raise PlatformError(f"场站编码 {code} 已存在", code="SITE_CODE_TAKEN",
                                status_code=409)
        return code
    base = code_for(name)
    code, n = base, 1
    while db.query(Site).filter(Site.code == code).first():
        n += 1
        code = f"{base}-{n}"
    return code


def get_site(db: Session, site_id: int | None) -> Site | None:
    if site_id is None:
        return None
    return db.get(Site, int(site_id))


def require_site(db: Session, site_id: int) -> Site:
    site = db.get(Site, int(site_id))
    if site is None:
        raise NotFound(f"场站不存在：{site_id}")
    return site


def default_site_id(db: Session) -> int | None:
    """默认站：历史“默认场站”的 code=default；没有就取最早建的场站。"""
    row = db.query(Site).filter(Site.code == "default").first()
    if row is None:
        row = db.query(Site).order_by(Site.id).first()
    return row.id if row is not None else None


def assert_no_cross_site(
    *,
    run_site: int | None = None,
    robot_site: int | None = None,
    map_site: int | None = None,
    template_site: int | None = None,
) -> None:
    """下发前的硬边界：四个归属只要有两个非空且不相等，就是跨站。

    只比较非空值：历史数据（迁移前没有 site_id）不能因为"没填"被误杀；
    一旦两边都有值就必须一致，不再降级成 warning。
    """
    pairs = (
        ("执行记录", run_site, "设备", robot_site),
        ("执行记录", run_site, "地图", map_site),
        ("模板", template_site, "地图", map_site),
        ("模板", template_site, "设备", robot_site),
    )
    for label_a, a, label_b, b in pairs:
        if a is None or b is None:
            continue
        if int(a) != int(b):
            raise PlatformError(
                f"跨站下发被拒绝：{label_a}属于场站 #{a}，{label_b}属于场站 #{b}",
                code="CROSS_SITE", status_code=409,
            )


def resolve_site_id(
    db: Session,
    *,
    map_id: int | None,
    site_id: int | None = None,
    robot_id: int | None = None,
    current: int | None = None,
) -> int | None:
    """推导模板/执行记录的 site_id，并在跨站时抛 409。

    优先级：map.site_id > 显式 site_id > 默认设备 site_id > 原值。
    任何两个非空来源不一致都拒绝——这就是"跨站模板"的入口闸门。
    """
    target = current

    if map_id is not None:
        map_row = db.get(PlatformMap, int(map_id))
        if map_row is None:
            raise BadRequest(f"地图不存在：{map_id}", code="NO_MAP")
        if map_row.site_id is not None:
            if site_id is not None and int(site_id) != int(map_row.site_id):
                raise PlatformError(
                    f"地图 #{map_id} 属于场站 #{map_row.site_id}，与请求的场站 #{site_id} 不一致",
                    code="CROSS_SITE", status_code=409)
            target = int(map_row.site_id)

    if site_id is not None:
        require_site(db, site_id)
        if target is not None and int(site_id) != int(target):
            raise PlatformError(
                f"场站 #{site_id} 与地图/设备所属场站 #{target} 不一致",
                code="CROSS_SITE", status_code=409)
        target = int(site_id)

    if robot_id is not None:
        robot = db.get(Robot, int(robot_id))
        if robot is None:
            raise BadRequest(f"设备不存在：{robot_id}", code="NO_ROBOT")
        if robot.site_id is not None:
            if target is not None and int(robot.site_id) != int(target):
                raise PlatformError(
                    f"设备 #{robot_id} 属于场站 #{robot.site_id}，与目标场站 #{target} 不一致",
                    code="CROSS_SITE", status_code=409)
            target = int(robot.site_id)

    return target
