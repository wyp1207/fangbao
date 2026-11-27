"""迁移 0031：场站（site）+ 设备/地图/模板/任务的场站边界。

问题：之前只有 `robot.station` / `platform_map.station` 两个自由文本，设备、地图、
模板、执行记录之间没有可校验的归属，跨站下发只能靠人盯。0031 引入 `site`，并把
历史数据按 station 去重回填——只加列、只回填，不删任何一行。

回填规则：
- site：robot.station ∪ platform_map.station，去重后各建一个场站（code = slug/hash）
- robot.site_id / platform_map.site_id ← 同名场站
- task_template.site_id ← 其 map 的 site；无 map 时跟随默认设备；都没有落默认站
- task_run.site_id ← robot.site_id；无设备时跟随模板；都没有落默认站
- task_run.map_id ← template.map_id（有模板时）

幂等：表/列已存在就跳过，只补 site_id IS NULL 的行；重复执行结果一致。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

DEFAULT_STATION = "默认场站"


def _code_for(name: str) -> str:
    """把场站名变成稳定 code：ASCII 走 slug，中文走短 hash。

    "默认场站" 固定为 default，给“无归属数据”一个稳定落点（也方便人读日志）。
    """
    text = (name or "").strip()
    if text == DEFAULT_STATION:
        return "default"
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if slug:
        return slug[:64]
    return "site-" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def _cols(insp, table: str) -> set[str]:
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _add_column(table: str, column: sa.Column) -> None:
    insp = sa.inspect(op.get_bind())
    if column.name in _cols(insp, table):
        return
    op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("site"):
        op.create_table(
            "site",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("code", sa.String(64), nullable=False, unique=True),
            sa.Column("address", sa.String(200), nullable=True),
            sa.Column("status", sa.Integer, nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )
        insp = sa.inspect(bind)

    # ---- 只加列，不改既有列；robot.robot_id 等历史列一律保留 ----
    if insp.has_table("robot"):
        _add_column("robot", sa.Column("site_id", sa.Integer, nullable=True))
        _add_column("robot", sa.Column("current_map_id", sa.Integer, nullable=True))
    if insp.has_table("platform_map"):
        _add_column("platform_map", sa.Column("site_id", sa.Integer, nullable=True))
    if insp.has_table("task_template"):
        _add_column("task_template", sa.Column("site_id", sa.Integer, nullable=True))
    if insp.has_table("task_run"):
        _add_column("task_run", sa.Column("site_id", sa.Integer, nullable=True))
        _add_column("task_run", sa.Column("map_id", sa.Integer, nullable=True))
        _add_column("task_run", sa.Column("batch_id", sa.String(64), nullable=True))
        _add_column("task_run", sa.Column("from_seq", sa.Integer, nullable=False,
                                          server_default="0"))
        _add_column("task_run", sa.Column("retry_of", sa.Integer, nullable=True))

    # ---- 从 station 去重建站 ----
    station_rows: list[tuple[str, str]] = []   # (station, 来源表)
    if insp.has_table("robot"):
        for (station,) in bind.execute(sa.text(
                "select station from robot order by id")):
            if station and station.strip():
                station_rows.append((station.strip(), "robot"))
    if insp.has_table("platform_map"):
        for (station,) in bind.execute(sa.text(
                "select station from platform_map order by id")):
            if station and station.strip():
                station_rows.append((station.strip(), "platform_map"))

    site_id_by_name: dict[str, int] = {}
    for name, _src in station_rows:
        if name in site_id_by_name:
            continue
        row = bind.execute(sa.text("select id from site where name = :n"),
                           {"n": name}).first()
        if row is not None:
            site_id_by_name[name] = int(row[0])
            continue
        base = _code_for(name)
        code, n = base, 1
        while bind.execute(sa.text("select 1 from site where code = :c"),
                           {"c": code}).first() is not None:
            n += 1
            code = f"{base}-{n}"
        bind.execute(
            sa.text("insert into site (name, code, status, created_at) "
                    "values (:n, :c, 1, :t)"),
            {"n": name, "c": code, "t": datetime.now()},
        )
        site_id_by_name[name] = int(
            bind.execute(sa.text("select id from site where code = :c"),
                         {"c": code}).scalar())

    # ---- 回填：设备 / 地图 ----
    robot_site: dict[int, int | None] = {}
    if insp.has_table("robot"):
        for rid, station in bind.execute(sa.text(
                "select id, station from robot order by id")):
            sid = site_id_by_name.get((station or "").strip())
            robot_site[int(rid)] = sid
            if sid is not None:
                bind.execute(
                    sa.text("update robot set site_id = :s "
                            "where id = :i and site_id is null"),
                    {"s": sid, "i": rid},
                )

    map_site: dict[int, int | None] = {}
    if insp.has_table("platform_map"):
        for mid, station in bind.execute(sa.text(
                "select id, station from platform_map order by id")):
            sid = site_id_by_name.get((station or "").strip())
            map_site[int(mid)] = sid
            if sid is not None:
                bind.execute(
                    sa.text("update platform_map set site_id = :s "
                            "where id = :i and site_id is null"),
                    {"s": sid, "i": mid},
                )

    # 默认站：优先 code=default（历史“默认场站”），否则第一个场站
    row = bind.execute(sa.text("select id from site where code = 'default'")).first()
    if row is None:
        row = bind.execute(sa.text("select id from site order by id")).first()
    default_site = int(row[0]) if row is not None else None

    # ---- 回填：模板 ----
    tpl_site: dict[int, int | None] = {}
    tpl_map: dict[int, int | None] = {}
    if insp.has_table("task_template"):
        for tid, map_id, robot_id in bind.execute(sa.text(
                "select id, map_id, robot_id from task_template order by id")):
            sid = map_site.get(int(map_id)) if map_id else None
            if sid is None and robot_id:
                sid = robot_site.get(int(robot_id))
            if sid is None:
                sid = default_site
            tpl_site[int(tid)] = sid
            tpl_map[int(tid)] = int(map_id) if map_id else None
            if sid is not None:
                bind.execute(
                    sa.text("update task_template set site_id = :s "
                            "where id = :i and site_id is null"),
                    {"s": sid, "i": tid},
                )

    # ---- 回填：执行记录 ----
    if insp.has_table("task_run"):
        for rid, robot_id, template_id in bind.execute(sa.text(
                "select id, robot_id, template_id from task_run order by id")):
            sid = robot_site.get(int(robot_id)) if robot_id else None
            if sid is None and template_id:
                sid = tpl_site.get(int(template_id))
            if sid is None:
                sid = default_site
            tpl_map_id = tpl_map.get(int(template_id)) if template_id else None
            bind.execute(
                sa.text("update task_run set site_id = :s, "
                        "map_id = coalesce(map_id, :m) where id = :i"),
                {"s": sid, "m": tpl_map_id, "i": rid},
            )


def downgrade() -> None:
    """降级只撤新增列与 site 表；不动既有业务数据。"""
    insp = sa.inspect(op.get_bind())
    cols = {
        "robot": ["site_id", "current_map_id"],
        "platform_map": ["site_id"],
        "task_template": ["site_id"],
        "task_run": ["site_id", "map_id", "batch_id", "from_seq", "retry_of"],
    }
    for table, names in cols.items():
        if not insp.has_table(table):
            continue
        have = _cols(insp, table)
        drop = [n for n in names if n in have]
        if not drop:
            continue
        with op.batch_alter_table(table) as batch:
            for n in drop:
                batch.drop_column(n)
    if insp.has_table("site"):
        op.drop_table("site")
