"""AI 结果查询接口：字段、过滤、stats 聚合。

真实回调（.170）写入的字段与手工推送（POST /ai/results）不一样：
`camera_id` 是平台相机台账，真实回调只有盒子侧的 `external_camera_id`。
页面要按相机/置信度/时间筛，顶部统计卡要总数/今日/P1/P2，所以这里既锁字段
契约，也锁 stats 的聚合口径（P1=critical、P2=warn，只算真建了告警的结果）。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

import pytest

from app.db.init import create_all
from app.db.session import SessionLocal
from app.models.ai import AiResult
from app.models.alarm import AlarmRecord

CAMERA_NAMES = {12: "dog", 13: "dog-云台", 14: "室外"}


@pytest.fixture(scope="module", autouse=True)
def _schema_and_clean():
    create_all()
    # 本文件对 total/today/分组做精确断言：先清空，避免别的用例的残留行影响口径
    with SessionLocal() as db:
        db.query(AiResult).delete()
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(AiResult).delete()
        db.commit()


@pytest.fixture
def created():
    ids: list[int] = []
    yield ids
    if ids:
        with SessionLocal() as db:
            db.query(AiResult).filter(AiResult.id.in_(ids)).delete(synchronize_session=False)
            db.commit()


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


def _make(db, ids: list[int], *, camera: int | None = 13, algorithm: str = "行人闯入",
          confidence: float = 0.9, ts: datetime | None = None,
          boxes: list[dict] | None = None, review_state: str | None = None,
          source_url: str | None = None, image_path: str | None = None,
          external_algorithm_id: int | None = 101, source_id: int = 1,
          alarm: AlarmRecord | None = None) -> AiResult:
    row = AiResult(
        source_id=source_id,
        external_event_id=uuid.uuid4().hex,
        algorithm=algorithm,
        external_camera_id=camera,
        external_camera_name=CAMERA_NAMES.get(camera),
        external_algorithm_id=external_algorithm_id,
        confidence=confidence,
        ts=ts or datetime.now().replace(microsecond=0),
        boxes_json=json.dumps(boxes, ensure_ascii=False) if boxes else None,
        review_state=review_state,
        source_url=source_url,
        image_path=image_path,
    )
    if alarm is not None:
        db.add(alarm)
        db.flush()
        row.alarm_id = alarm.id
    db.add(row)
    db.commit()
    db.refresh(row)
    ids.append(row.id)
    return row


def _alarm(db, level: str) -> AlarmRecord:
    alarm = AlarmRecord(metric="ai_测试", level=level, message=f"{level} 测试告警")
    db.add(alarm)
    db.commit()
    db.refresh(alarm)
    return alarm


def _items(client, ids: list[int], **params) -> list[dict]:
    r = client.get("/api/v1/ai/results", params={"limit": 200, **params})
    assert r.status_code == 200, r.text
    return [item for item in r.json()["items"] if item["id"] in ids]


# ---------- 1. 字段契约 ----------


def test_result_fields_expose_external_camera_and_evidence(auth_client, db, created):
    row = _make(
        db, created,
        camera=13, algorithm="安全帽识别", confidence=0.8123,
        boxes=[{"label": "person", "score": 0.8123, "x": 10, "y": 20}],
        review_state="confirmed",
        source_url="http://192.168.1.170:8081/a.jpg",
        image_path="ai_images/callback/20261118/x.jpg",
        external_algorithm_id=7,
    )

    item = _items(auth_client, created)[0]

    assert item["id"] == row.id
    assert item["camera_name"] == "dog-云台"
    assert item["external_camera_id"] == 13
    assert item["external_algorithm_id"] == 7
    assert item["review_state"] == "confirmed"
    assert item["source_url"] == "http://192.168.1.170:8081/a.jpg"
    assert item["boxes"] == [{"label": "person", "score": 0.8123, "x": 10, "y": 20}]
    assert item["image"] == f"/api/v1/ai/results/{row.id}/image"
    assert item["confidence"] == pytest.approx(0.8123)
    assert item["demo"] is False          # 真实回调（source_id=1）不算演示


def test_result_demo_flag_comes_from_source_id(auth_client, db, created):
    real = _make(db, created, camera=12, algorithm="行人闯入")
    demo = _make(db, created, camera=14, algorithm="火焰识别", source_id=99)

    items = {i["id"]: i for i in _items(auth_client, created)}

    assert items[real.id]["demo"] is False
    assert items[demo.id]["demo"] is True


def test_missing_optional_fields_are_null_not_error(auth_client, db, created):
    _make(db, created, camera=None, algorithm="未知算法", boxes=None,
          review_state=None, source_url=None, image_path=None)

    item = _items(auth_client, created)[0]

    assert item["camera_name"] is None
    assert item["external_camera_id"] is None
    assert item["source_url"] is None
    assert item["review_state"] is None
    assert item["boxes"] == []
    assert item["image"] is None


# ---------- 2. 过滤 ----------


def test_filter_by_external_camera_id(auth_client, db, created):
    _make(db, created, camera=12)
    _make(db, created, camera=13)
    _make(db, created, camera=14)

    dog = _items(auth_client, created, external_camera_id=12)
    gimbal = _items(auth_client, created, external_camera_id=13)

    assert [i["external_camera_id"] for i in dog] == [12]
    assert [i["external_camera_id"] for i in gimbal] == [13]
    assert dog[0]["camera_name"] == "dog"


def test_filter_by_min_confidence(auth_client, db, created):
    _make(db, created, camera=12, confidence=0.2)
    _make(db, created, camera=13, confidence=0.55)
    _make(db, created, camera=14, confidence=0.91)

    kept = _items(auth_client, created, min_confidence=0.6)

    assert [i["confidence"] for i in kept] == [0.91]


def test_filter_by_since_is_inclusive(auth_client, db, created):
    now = datetime.now().replace(microsecond=0)
    old = _make(db, created, camera=12, ts=now - timedelta(days=2))
    fresh = _make(db, created, camera=13, ts=now - timedelta(minutes=5))

    since = (now - timedelta(days=1)).isoformat()
    kept = _items(auth_client, created, since=since)

    assert [i["id"] for i in kept] == [fresh.id]
    assert old.id not in [i["id"] for i in kept]


def test_filter_by_since_accepts_utc_z_suffix(auth_client, db, created):
    from datetime import timezone

    now = datetime.now().replace(microsecond=0)
    fresh = _make(db, created, camera=12, ts=now - timedelta(minutes=5))
    old = _make(db, created, camera=13, ts=now - timedelta(days=2))

    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    kept = _items(auth_client, created, since=since)

    assert [i["id"] for i in kept] == [fresh.id]
    assert old.id not in [i["id"] for i in kept]


def test_filters_combine(auth_client, db, created):
    _make(db, created, camera=13, algorithm="行人闯入", confidence=0.95)
    _make(db, created, camera=13, algorithm="安全帽识别", confidence=0.95)
    _make(db, created, camera=12, algorithm="行人闯入", confidence=0.95)

    kept = _items(auth_client, created, external_camera_id=13,
                  algorithm="行人闯入", min_confidence=0.8)

    assert len(kept) == 1
    assert kept[0]["camera_name"] == "dog-云台"


def test_results_sorted_by_id_desc(auth_client, db, created):
    ids = [
        _make(db, created, camera=12).id,
        _make(db, created, camera=13).id,
        _make(db, created, camera=14).id,
    ]

    kept = _items(auth_client, created)

    assert [i["id"] for i in kept] == sorted(ids, reverse=True)


def test_limit_is_capped_at_200(auth_client, db, created):
    rows = [
        AiResult(source_id=1, external_event_id=f"limit-{uuid.uuid4().hex}",
                 algorithm="批量", external_camera_id=14,
                 external_camera_name="室外", confidence=0.5, ts=datetime.now())
        for _ in range(205)
    ]
    db.add_all(rows)
    db.commit()

    r = auth_client.get("/api/v1/ai/results", params={"limit": 1000})

    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) == 200
    # 清理本用例额外造的 205 行，别污染同文件里对 total 的精确断言
    db.query(AiResult).filter(AiResult.algorithm == "批量").delete(synchronize_session=False)
    db.commit()


# ---------- 3. stats ----------


def test_stats_totals_groups_and_p1_p2(auth_client, db, created):
    today = datetime.now().replace(microsecond=0)
    yesterday = today - timedelta(days=1)

    _make(db, created, camera=12, algorithm="行人闯入", ts=today,
          alarm=_alarm(db, "critical"))
    _make(db, created, camera=12, algorithm="行人闯入", ts=today)
    _make(db, created, camera=13, algorithm="安全帽识别", ts=today,
          alarm=_alarm(db, "warn"))
    _make(db, created, camera=13, algorithm="安全帽识别", ts=today)
    _make(db, created, camera=13, algorithm="安全帽识别", ts=today)
    _make(db, created, camera=14, algorithm="火焰识别", ts=yesterday)

    # 12 个只出现一次的算法：验证 top 10 截断
    for i in range(12):
        _make(db, created, camera=14, algorithm=f"算法{i:02d}", ts=today)

    r = auth_client.get("/api/v1/ai/results/stats")
    assert r.status_code == 200, r.text
    stats = r.json()

    assert stats["total"] == 18
    assert stats["today"] == 17          # 昨天那条火焰不算今日
    assert stats["p1"] == 1              # critical
    assert stats["p2"] == 1              # warn
    assert stats["demo"] == 0            # 本用例没有 source_id=99 的行

    cameras = {c["external_camera_id"]: c for c in stats["by_camera"]}
    assert cameras[14]["count"] == 13    # 火焰 1 + 12 个算法
    assert cameras[13]["count"] == 3
    assert cameras[12]["count"] == 2
    assert cameras[13]["camera_name"] == "dog-云台"
    assert cameras[14]["camera_name"] == "室外"

    algorithms = stats["by_algorithm"]
    assert len(algorithms) == 10         # top 10，不是全部 15 种
    assert algorithms[0] == {"algorithm": "安全帽识别", "count": 3}
    assert algorithms[1] == {"algorithm": "行人闯入", "count": 2}


def test_stats_counts_demo_rows_from_source_id_99(auth_client, db, created):
    # 真实回调 2 条 + 演示种子 3 条：demo 只数 source_id=99，且计入 total
    _make(db, created, camera=12, algorithm="行人闯入", source_id=1)
    _make(db, created, camera=13, algorithm="安全帽识别", source_id=1)
    for i in range(3):
        _make(db, created, camera=14, algorithm="火焰识别", source_id=99)

    stats = auth_client.get("/api/v1/ai/results/stats").json()

    assert stats["demo"] == 3
    assert stats["total"] == 5


def test_stats_is_zero_safe_on_empty_db(auth_client):
    # 模块级 fixture 已清空；不创建任何行
    stats = auth_client.get("/api/v1/ai/results/stats").json()

    assert stats["total"] == 0
    assert stats["today"] == 0
    assert stats["p1"] == 0
    assert stats["p2"] == 0
    assert stats["demo"] == 0
    assert stats["by_camera"] == []
    assert stats["by_algorithm"] == []
