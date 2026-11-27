"""场站（site）后端 P0 的验收测试。

覆盖：
1. 迁移 0031 建 site 并回填 robot/platform_map/task_template/task_run，且不丢数据；
2. GET /sites（空库不造假数据）+ site CRUD；
3. devices / maps / task-templates / task-runs 按 site_id 过滤；
4. 模板 site 由 map 推导、跨站设备/地图被拒；
5. 下发时 run.site == robot.site == map.site、template.site == map.site，否则 409 CROSS_SITE；
6. current_map_id 优先 robot.current_map_id，其次同站激活图，最后全局激活图；
7. map.strict_check 默认 True，跨图点位直接 409。
"""

from __future__ import annotations

import io
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- 迁移回填

def _alembic(db_path: Path, revision: str) -> None:
    env = dict(os.environ)
    env["JC_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
    env["JC_ENV"] = "test"
    env["PYTHONPATH"] = str(SERVER_ROOT)
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=SERVER_ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    assert r.returncode == 0, f"alembic upgrade {revision} 失败:\n{r.stdout}\n{r.stderr}"


def _cols(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"pragma table_info({table})")}


def test_site_migration_backfill(tmp_path):
    """0031 回填：3 台设备 / 4 张图 / 26 条 run 全部有 site_id，且一行不少。"""
    db = tmp_path / "site_mig.db"
    _alembic(db, "0030")

    conn = sqlite3.connect(db)
    conn.executemany(
        "insert into robot(id, name, station) values(?,?,?)",
        [(1, "R-甲", "甲站"), (2, "R-乙", "乙站"), (3, "R-丙", "丙站")],
    )
    conn.executemany(
        "insert into platform_map(id, name, station, image_path, is_active) "
        "values(?,?,?,?,1)",
        [(1, "M-甲", "甲站", "m1.png"), (2, "M-乙1", "乙站", "m2.png"),
         (3, "M-乙2", "乙站", "m3.png"), (4, "M-丙", "丙站", "m4.png")],
    )
    templates = [
        (1, "T-map1", 1, 1),      # map 1 → 甲
        (2, "T-map2", 2, None),   # map 2 → 乙
        (3, "T-map3", 3, 2),      # map 3 → 乙
        (4, "T-map4", 4, None),   # map 4 → 丙
        (5, "T-nomap", None, 2),  # 无图、绑定乙站设备
    ]
    conn.executemany(
        "insert into task_template(id, name, map_id, robot_id, actions_json) "
        "values(?,?,?,?, '[]')", templates,
    )
    runs = []
    for i in range(1, 27):
        robot_id = (i % 3) + 1            # 2,3,1 轮转，全部有设备
        tpl_id = (i % 5) + 1              # 1..5
        if i % 6 == 0:                    # 每 6 条有一台无设备
            robot_id = None
        if i % 4 == 0:                    # 每 4 条有一条无模板
            tpl_id = None
        runs.append((i, f"R{i}", tpl_id, robot_id))
    conn.executemany(
        "insert into task_run(id, name, template_id, robot_id, status) "
        "values(?,?,?,?, 'planned')", runs,
    )
    conn.commit()
    conn.close()

    _alembic(db, "head")

    conn = sqlite3.connect(db)
    assert conn.execute("select version_num from alembic_version").fetchone()[0] == "0032"
    # 不丢数据
    assert conn.execute("select count(*) from robot").fetchone()[0] == 3
    assert conn.execute("select count(*) from platform_map").fetchone()[0] == 4
    assert conn.execute("select count(*) from task_template").fetchone()[0] == 5
    assert conn.execute("select count(*) from task_run").fetchone()[0] == 26

    # 新列都在
    assert {"site_id", "current_map_id"} <= _cols(conn, "robot")
    assert "site_id" in _cols(conn, "platform_map")
    assert "site_id" in _cols(conn, "task_template")
    assert {"site_id", "map_id", "batch_id", "from_seq", "retry_of"} <= _cols(conn, "task_run")

    # 去重：甲/乙/丙 共 3 个场站
    sites = conn.execute("select id, name, code, status from site order by id").fetchall()
    assert len(sites) == 3, sites
    assert {s[1] for s in sites} == {"甲站", "乙站", "丙站"}
    assert all(s[2] for s in sites) and len({s[2] for s in sites}) == 3
    assert all(s[3] == 1 for s in sites)
    site_by_name = {s[1]: s[0] for s in sites}

    # 设备/地图全部回填
    assert conn.execute("select count(*) from robot where site_id is null").fetchone()[0] == 0
    assert conn.execute("select count(*) from platform_map where site_id is null").fetchone()[0] == 0
    assert conn.execute("select count(*) from task_template where site_id is null").fetchone()[0] == 0

    r_site = dict(conn.execute("select id, site_id from robot").fetchall())
    m_site = dict(conn.execute("select id, site_id from platform_map").fetchall())
    t_site = dict(conn.execute("select id, site_id from task_template").fetchall())
    t_map = dict(conn.execute("select id, map_id from task_template").fetchall())
    assert r_site[1] == site_by_name["甲站"]
    assert m_site[1] == site_by_name["甲站"]
    assert t_site[1] == m_site[1]
    assert t_site[2] == m_site[2]
    assert t_site[5] == r_site[2]          # 无图模板跟随默认设备所在站

    # run：有设备跟设备；无设备跟模板；都没有落默认站
    default_site = sites[0][0]
    run_rows = conn.execute(
        "select id, robot_id, template_id, site_id, map_id from task_run order by id"
    ).fetchall()
    assert len(run_rows) == 26
    for rid, robot_id, tpl_id, site_id, map_id in run_rows:
        assert site_id is not None, f"run {rid} 没回填 site_id"
        if robot_id is not None:
            assert site_id == r_site[robot_id], f"run {rid} site 与设备不一致"
            if tpl_id is not None:
                assert map_id == t_map[tpl_id], f"run {rid} map 未取模板"
        elif tpl_id is not None:
            assert site_id == t_site[tpl_id], f"run {rid} site 未跟随模板"
        else:
            assert site_id == default_site
    # from_seq 默认 0，batch/retry 留空
    assert conn.execute("select count(*) from task_run where from_seq != 0").fetchone()[0] == 0
    assert conn.execute("select count(*) from task_run where batch_id is not null").fetchone()[0] == 0

    # 幂等：再跑一次不报错、不重复建站
    conn.close()
    _alembic(db, "head")
    conn = sqlite3.connect(db)
    assert conn.execute("select count(*) from site").fetchone()[0] == 3
    assert conn.execute("select count(*) from task_run").fetchone()[0] == 26
    conn.close()


# ---------------------------------------------------------------- API 夹具

@pytest.fixture
def site_scope(auth_client):
    """记录基线，测试后清掉本用例造的场站/地图/模板/run，避免污染其他用例。"""
    from sqlalchemy import func

    from app.db.session import SessionLocal
    from app.models.map_library import PlatformMap, PointDraft
    from app.models.robot import Robot
    from app.models.site import Site
    from app.models.task_run import TaskEvent, TaskRun, TaskRunStep
    from app.models.task_template import TaskTemplate

    with SessionLocal() as db:
        base = {
            "site": db.scalar(func.max(Site.id)) or 0,
            "platform_map": db.scalar(func.max(PlatformMap.id)) or 0,
            "task_template": db.scalar(func.max(TaskTemplate.id)) or 0,
            "task_run": db.scalar(func.max(TaskRun.id)) or 0,
            "robot": db.scalar(func.max(Robot.id)) or 0,
        }
        r1 = db.get(Robot, 1)
        old = (r1.site_id, r1.current_map_id) if r1 else (None, None)

    try:
        yield base
    finally:
        with SessionLocal() as db:
            run_ids = [r.id for r in db.query(TaskRun).filter(TaskRun.id > base["task_run"])]
            if run_ids:
                # 事件也要清：只删 run 会让 SQLite 复用 id，残留事件污染别的用例
                db.query(TaskEvent).filter(TaskEvent.run_id.in_(run_ids)).delete(
                    synchronize_session=False)
                db.query(TaskRunStep).filter(TaskRunStep.run_id.in_(run_ids)).delete(
                    synchronize_session=False)
            db.query(TaskRun).filter(TaskRun.id > base["task_run"]).delete(
                synchronize_session=False)
            db.query(TaskTemplate).filter(TaskTemplate.id > base["task_template"]).delete(
                synchronize_session=False)
            map_ids = [m.id for m in db.query(PlatformMap)
                       .filter(PlatformMap.id > base["platform_map"])]
            if map_ids:
                db.query(PointDraft).filter(PointDraft.map_id.in_(map_ids)).delete(
                    synchronize_session=False)
            db.query(PlatformMap).filter(PlatformMap.id > base["platform_map"]).delete(
                synchronize_session=False)
            db.query(Site).filter(Site.id > base["site"]).delete(synchronize_session=False)
            db.query(Robot).filter(Robot.id > base["robot"]).delete(synchronize_session=False)
            r1 = db.get(Robot, 1)
            if r1 is not None:
                r1.site_id, r1.current_map_id = old
            db.commit()
        # 写开关经 API 关闭：顺带让 settings 的 2 秒缓存失效，别污染后面的用例
        auth_client.put("/api/v1/settings", json={"values": {"robot.write_enabled": False}})


def _make_site(client, name: str, code: str | None = None) -> dict:
    body = {"name": name}
    if code:
        body["code"] = code
    r = client.post("/api/v1/sites", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _make_map(client, name: str, site_id: int | None = None, active: bool = True) -> dict:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(buf, format="PNG")
    data = {"name": name, "resolution": "0.05"}
    if site_id is not None:
        data["site_id"] = str(site_id)
    r = client.post("/api/v1/maps/library",
                    files={"file": (f"{name}.png", buf.getvalue(), "image/png")},
                    data=data)
    assert r.status_code == 200, r.text
    row = r.json()
    if not active:
        p = client.patch(f"/api/v1/maps/library/{row['id']}", json={"is_active": False})
        assert p.status_code == 200, p.text
        row = p.json()
    return row


def _make_point(client, map_id: int, name: str, x: float = 1.0, y: float = 1.0) -> dict:
    r = client.post(f"/api/v1/maps/library/{map_id}/points",
                    json={"name": name, "x": x, "y": y})
    assert r.status_code == 200, r.text
    return r.json()


def _make_template(client, name: str, map_id: int | None, points: list[dict],
                   **extra) -> dict:
    body = {
        "name": name,
        "actions": [{"point_id": p["id"], "action": "photo"} for p in points],
    }
    if map_id is not None:
        body["map_id"] = map_id
    body.update(extra)
    r = client.post("/api/v1/task-templates", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- GET /sites

def test_sites_list_requires_login_and_no_fake_data(client):
    from fastapi.testclient import TestClient

    from app.db.session import SessionLocal
    from app.models.site import Site

    # 会话级 client 可能已被其他用例登录过：未登录校验必须用干净客户端
    anon = TestClient(client.app)
    assert anon.get("/api/v1/sites").status_code == 401

    with SessionLocal() as db:
        db.query(Site).delete()      # 明确构造“空场站表”
        db.commit()
        assert db.query(Site).count() == 0

    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    client.headers.update({"X-CSRF-Token": r.json()["csrf_token"]})

    assert client.get("/api/v1/sites").json() == []
    with SessionLocal() as db:
        assert db.query(Site).count() == 0     # 读接口不能顺手造假数据


def test_site_create_list_and_filters(site_scope, auth_client):
    from app.db.session import SessionLocal
    from app.models.robot import Robot

    a = _make_site(auth_client, "甲场站", "site-a")
    b = _make_site(auth_client, "乙场站", "site-b")
    assert a["status"] == 1 and "created_at" in a

    listed = auth_client.get("/api/v1/sites").json()
    ids = {s["id"] for s in listed}
    assert {a["id"], b["id"]} <= ids

    dup = auth_client.post("/api/v1/sites", json={"name": "重复码", "code": "site-a"})
    assert dup.status_code == 409
    assert dup.json()["code"] == "SITE_CODE_TAKEN"

    # 改地址/状态
    p = auth_client.patch(f"/api/v1/sites/{a['id']}", json={"address": "1 号门", "status": 0})
    assert p.status_code == 200 and p.json()["address"] == "1 号门" and p.json()["status"] == 0
    auth_client.patch(f"/api/v1/sites/{a['id']}", json={"status": 1})

    # 设备：把默认设备划到甲站
    with SessionLocal() as db:
        r1 = db.get(Robot, 1)
        r1.site_id = a["id"]
        db.commit()

    ma = _make_map(auth_client, "甲站地图", site_id=a["id"])
    mb = _make_map(auth_client, "乙站地图", site_id=b["id"])
    pa = _make_point(auth_client, ma["id"], "甲点")
    _make_point(auth_client, mb["id"], "乙点")

    ta = _make_template(auth_client, "甲站模板", ma["id"], [pa])
    assert ta["site_id"] == a["id"]
    from app.models.site import Site  # noqa: F401  确保模型已加载

    run = auth_client.post("/api/v1/task-runs", json={"template_id": ta["id"], "robot_id": 1})
    assert run.status_code == 200, run.text
    assert run.json()["site_id"] == a["id"]
    assert run.json()["map_id"] == ma["id"]
    assert run.json()["from_seq"] == 0
    assert run.json()["batch_id"] is None and run.json()["retry_of"] is None

    # 过滤：甲站只看到自己的
    dev_a = auth_client.get(f"/api/v1/devices?site_id={a['id']}").json()
    assert [d["id"] for d in dev_a] == [1]
    assert dev_a[0]["site_id"] == a["id"]
    assert auth_client.get(f"/api/v1/devices?site_id={b['id']}").json() == []

    maps_a = auth_client.get(f"/api/v1/maps/library?site_id={a['id']}").json()
    assert {m["id"] for m in maps_a} == {ma["id"]}
    assert all(m["site_id"] == a["id"] for m in maps_a)
    maps_b = auth_client.get(f"/api/v1/maps/library?site_id={b['id']}").json()
    assert {m["id"] for m in maps_b} == {mb["id"]}
    assert len(auth_client.get("/api/v1/maps/library").json()) >= 2

    tpl_a = auth_client.get(f"/api/v1/task-templates?site_id={a['id']}").json()
    assert {t["id"] for t in tpl_a} == {ta["id"]}
    tpl_b = auth_client.get(f"/api/v1/task-templates?site_id={b['id']}").json()
    assert tpl_b == []

    runs_a = auth_client.get(f"/api/v1/task-runs?site_id={a['id']}").json()
    assert run.json()["id"] in {i["id"] for i in runs_a["items"]}
    assert all(i["site_id"] == a["id"] for i in runs_a["items"])
    runs_b = auth_client.get(f"/api/v1/task-runs?site_id={b['id']}").json()
    assert run.json()["id"] not in {i["id"] for i in runs_b["items"]}


# ---------------------------------------------------------------- 模板 site 推导

def test_template_site_derivation_and_cross_site(site_scope, auth_client):
    from app.db.session import SessionLocal
    from app.models.robot import Robot

    a = _make_site(auth_client, "甲场站")
    b = _make_site(auth_client, "乙场站")
    with SessionLocal() as db:
        r1 = db.get(Robot, 1)
        r1.site_id = a["id"]
        rb = Robot(name="乙站设备", ip="127.0.0.2", port=3546, ws_port=3547,
                   mode="mock", station="乙场站", site_id=b["id"])
        db.add(rb)
        db.commit()
        rb_id = rb.id

    ma = _make_map(auth_client, "甲图", site_id=a["id"])
    mb = _make_map(auth_client, "乙图", site_id=b["id"])
    pa = _make_point(auth_client, ma["id"], "甲点")
    pb = _make_point(auth_client, mb["id"], "乙点")

    # map 属于甲站，却声明乙站 → 409
    bad = auth_client.post("/api/v1/task-templates", json={
        "name": "跨站模板", "map_id": ma["id"], "site_id": b["id"],
        "actions": [{"point_id": pa["id"], "action": "photo"}],
    })
    assert bad.status_code == 409 and bad.json()["code"] == "CROSS_SITE"

    # 默认设备不属于该站 → 409
    bad2 = auth_client.post("/api/v1/task-templates", json={
        "name": "跨站默认设备", "map_id": ma["id"], "default_robot_id": rb_id,
        "actions": [{"point_id": pa["id"], "action": "photo"}],
    })
    assert bad2.status_code == 409 and bad2.json()["code"] == "CROSS_SITE"

    # 不传 map，也不传设备 → 允许 site 为空（兼容老前端）
    ok0 = auth_client.post("/api/v1/task-templates", json={
        "name": "无站点模板", "actions": [{"point_id": pa["id"], "action": "photo"}],
    })
    assert ok0.status_code == 200, ok0.text

    # map 推导 site；default_robot_id 输出别名
    ok = _make_template(auth_client, "甲站模板", ma["id"], [pa], default_robot_id=1)
    assert ok["site_id"] == a["id"]
    assert ok["default_robot_id"] == 1
    assert ok["robot_id"] == ok["default_robot_id"]      # 兼容老字段

    # 改图：map 换到乙站，而默认设备在甲站 → 409
    upd = auth_client.patch(f"/api/v1/task-templates/{ok['id']}",
                            json={"map_id": mb["id"]})
    assert upd.status_code == 409 and upd.json()["code"] == "CROSS_SITE"

    # 显式 site 与 map 冲突 → 409
    upd2 = auth_client.patch(f"/api/v1/task-templates/{ok['id']}", json={"site_id": b["id"]})
    assert upd2.status_code == 409 and upd2.json()["code"] == "CROSS_SITE"

    # 正常改到乙站（同时换默认设备、点位）→ 200，site 跟随
    upd3 = auth_client.patch(f"/api/v1/task-templates/{ok['id']}", json={
        "map_id": mb["id"], "default_robot_id": rb_id,
        "actions": [{"point_id": pb["id"], "action": "photo"}],
    })
    assert upd3.status_code == 200, upd3.text
    assert upd3.json()["site_id"] == b["id"]
    assert upd3.json()["default_robot_id"] == rb_id


# ---------------------------------------------------------------- 下发校验

def test_dispatch_cross_site_409(site_scope, auth_client):
    from app.db.session import SessionLocal

    a = _make_site(auth_client, "甲场站")
    b = _make_site(auth_client, "乙场站")
    with SessionLocal() as db:
        from app.models.robot import Robot

        r1 = db.get(Robot, 1)
        r1.site_id = a["id"]
        db.commit()

    ma = _make_map(auth_client, "甲图", site_id=a["id"])
    mb = _make_map(auth_client, "乙图", site_id=b["id"], active=False)
    pa = _make_point(auth_client, ma["id"], "甲点")
    pb = _make_point(auth_client, mb["id"], "乙点")
    ta = _make_template(auth_client, "甲站模板", ma["id"], [pa])
    tb = _make_template(auth_client, "乙站模板", mb["id"], [pb])

    assert auth_client.put("/api/v1/settings", json={
        "values": {"robot.write_enabled": True}}).status_code == 200

    try:
        # 同站：放行
        run = auth_client.post("/api/v1/task-runs",
                               json={"template_id": ta["id"], "robot_id": 1}).json()
        dispatched = auth_client.post(f"/api/v1/task-runs/{run['id']}/dispatch")
        assert dispatched.status_code == 200, dispatched.text
        auth_client.post(f"/api/v1/task-runs/{run['id']}/cancel")

        # run 属乙站、车属甲站 → 409
        cross_run = auth_client.post("/api/v1/task-runs",
                                     json={"template_id": tb["id"], "robot_id": 1}).json()
        assert cross_run["site_id"] == b["id"]
        d1 = auth_client.post(f"/api/v1/task-runs/{cross_run['id']}/dispatch")
        assert d1.status_code == 409 and d1.json()["code"] == "CROSS_SITE"

        # 模板（乙站）直接发给甲站设备 → 409
        d2 = auth_client.post(f"/api/v1/task-templates/{tb['id']}/dispatch",
                              json={"robot_id": 1})
        assert d2.status_code == 409 and d2.json()["code"] == "CROSS_SITE"

        # 模板未绑定设备，允许显式传 robot_id（同站）
        ta2 = _make_template(auth_client, "未绑定模板", ma["id"], [pa])
        assert ta2["default_robot_id"] is None
        d3 = auth_client.post(f"/api/v1/task-templates/{ta2['id']}/dispatch",
                              json={"robot_id": 1})
        assert d3.status_code == 200, d3.text
        assert d3.json()["status"] == "running"
        auth_client.post(f"/api/v1/task-runs/{d3.json()['run_id']}/cancel")
    finally:
        auth_client.put("/api/v1/settings", json={"values": {"robot.write_enabled": False}})


# ---------------------------------------------------------------- current_map_id

def test_current_map_id_prefers_robot_then_site_then_global(site_scope, auth_client):
    from app.db.session import SessionLocal
    from app.models.map_library import PlatformMap
    from app.models.robot import Robot
    from app.models.site import Site
    from app.services.map_check import current_map_id

    a = _make_site(auth_client, "甲场站")
    b = _make_site(auth_client, "乙场站")

    with SessionLocal() as db:
        r1 = db.get(Robot, 1)
        r1.site_id = a["id"]
        r1.current_map_id = None

        ma = PlatformMap(name="甲站激活图", station="甲场站", image_path="a.png",
                         width=10, height=10, is_active=True, site_id=a["id"],
                         robot_map_name="jueying")
        ma2 = PlatformMap(name="甲站停用图", station="甲场站", image_path="a2.png",
                          width=10, height=10, is_active=False, site_id=a["id"])
        mb = PlatformMap(name="乙站激活图", station="乙场站", image_path="b.png",
                         width=10, height=10, is_active=True, site_id=b["id"],
                         robot_map_name="jueying")
        db.add_all([ma, ma2, mb])
        db.commit()
        ids = {"ma": ma.id, "ma2": ma2.id, "mb": mb.id}

        # 1) 显式 current_map_id 优先，即使它是别站的图
        r1.current_map_id = ids["mb"]
        db.commit()
        assert current_map_id(db, r1) == ids["mb"]

        # 2) current_map_id 失效（指向不存在的图）→ 同站激活图
        r1.current_map_id = 999999
        db.commit()
        assert current_map_id(db, r1) == ids["ma"]

        # 3) current_map_id 显式指定停用图也算数
        r1.current_map_id = ids["ma2"]
        db.commit()
        assert current_map_id(db, r1) == ids["ma2"]

        # 4) 没指定 → 同站激活图，而不是全局第一张
        r1.current_map_id = None
        db.commit()
        assert current_map_id(db, r1) == ids["ma"]

        # 5) 本站没有激活图 → 全局激活图（兼容旧数据）
        ma.is_active = False
        db.commit()
        first_active = (db.query(PlatformMap)
                        .filter(PlatformMap.is_active.is_(True))
                        .order_by(PlatformMap.id).first())
        expected_global = first_active.id if first_active is not None else None
        assert current_map_id(db, r1) == expected_global
        assert expected_global != ids["ma"]

        # 6) 不再读不存在的 current_map_name：带该属性的旧对象走全局逻辑
        class _Legacy:
            current_map_name = "jueying"

        assert current_map_id(db, _Legacy()) == expected_global
        assert not hasattr(Robot, "current_map_name")


# ---------------------------------------------------------------- strict_check

def test_strict_check_default_true_blocks_cross_map(site_scope, auth_client):
    from app.api.v1.settings import invalidate, load_all
    from app.db.session import SessionLocal
    from app.models.setting import set_value
    from app.services import settings_schema as schema

    assert schema.SCHEMA["map.strict_check"]["default"] is True
    invalidate()
    assert load_all()["map.strict_check"] is True

    a = _make_site(auth_client, "甲场站")
    with SessionLocal() as db:
        from app.models.robot import Robot

        r1 = db.get(Robot, 1)
        r1.site_id = a["id"]
        r1.current_map_id = None
        db.commit()

    m1 = _make_map(auth_client, "当前激活图", site_id=a["id"], active=True)
    m2 = _make_map(auth_client, "另一张图", site_id=a["id"], active=False)
    p2 = _make_point(auth_client, m2["id"], "别的图的点")

    # 模板不声明 map（老数据形态），点位在 m2；下发时激活图是 m1 → 跨图必须 409
    tpl = _make_template(auth_client, "跨图模板", None, [p2])
    run = auth_client.post("/api/v1/task-runs",
                           json={"template_id": tpl["id"], "robot_id": 1}).json()

    with SessionLocal() as db:
        set_value(db, "robot.write_enabled", True, who="test")
    invalidate()
    try:
        r = auth_client.post(f"/api/v1/task-runs/{run['id']}/dispatch")
        assert r.status_code == 409, r.text
        assert r.json()["code"] == "POINT_MAP_MISMATCH"
        assert "先切图或改点位" in r.json()["message"]
    finally:
        with SessionLocal() as db:
            set_value(db, "robot.write_enabled", False, who="test")
        invalidate()
