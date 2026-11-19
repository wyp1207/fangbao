"""告警详情看 AI 检测框图：GET /ai/results/by-alarm/{alarm_id}。

告警页的「图」按钮只对 metric 以 ai_ 开头的行出现；点开必须能拿到这条告警
关联的最新一条 AiResult，前端才有图、有框、有百分比标签。这条接口是
「告警 → 证据」的唯一入口，所以锁三件事：

1. 按 alarm_id 找回那一条，boxes / image 等字段原样透出（空 boxes 等于没框）；
2. 同一告警有多条结果时给最新的一条（回看要看到最近证据，不是最旧的）；
3. 没有关联结果时 404，不能返回空对象让前端画一个空弹层。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

import pytest

from app.db.init import create_all
from app.db.session import SessionLocal
from app.models.ai import AiResult

ALARM_ID = 42
BOXES = [
    {"class_id": 1, "score": 0.803,
     "rect": {"x": 800, "y": 300, "width": 400, "height": 700}},
]
IMAGE_PATH = "ai_images/demo/20261118/demo-0200.jpg"


@pytest.fixture(scope="module", autouse=True)
def _schema():
    create_all()
    yield


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def created(db):
    """本文件造的行，用例结束删干净，避免影响别的文件对 total 的断言。"""
    ids: list[int] = []
    yield ids
    if ids:
        db.query(AiResult).filter(AiResult.id.in_(ids)).delete(synchronize_session=False)
        db.commit()


def _make(db, ids: list[int], *, alarm_id: int = ALARM_ID, boxes: list[dict] | None = None,
          image_path: str | None = None, confidence: float = 0.803) -> AiResult:
    row = AiResult(
        source_id=1,
        external_event_id=uuid.uuid4().hex,
        algorithm="行人闯入",
        external_camera_id=12,
        external_camera_name="dog",
        external_algorithm_id=101,
        confidence=confidence,
        ts=datetime.now().replace(microsecond=0),
        boxes_json=json.dumps(boxes, ensure_ascii=False) if boxes is not None else None,
        image_path=image_path,
        alarm_id=alarm_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    ids.append(row.id)
    return row


def test_by_alarm_returns_linked_result_with_boxes_and_image(auth_client, db, created):
    row = _make(db, created, boxes=BOXES, image_path=IMAGE_PATH)

    r = auth_client.get(f"/api/v1/ai/results/by-alarm/{ALARM_ID}")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == row.id
    assert body["alarm_id"] == ALARM_ID
    assert body["boxes"] == BOXES
    assert body["boxes"], "前端靠 boxes 画检测框，空数组等于没有框"
    assert body["confidence"] == pytest.approx(0.803)
    assert body["image"] == f"/api/v1/ai/results/{row.id}/image"
    assert body["has_image"] is True
    # 告警页弹层标题要显示算法名和相机名
    assert body["camera_name"] == "dog"


def test_by_alarm_returns_latest_result_when_alarm_has_many(auth_client, db, created):
    _make(db, created, boxes=BOXES, image_path=IMAGE_PATH, confidence=0.51)
    newest = _make(db, created, boxes=BOXES, image_path=IMAGE_PATH, confidence=0.93)

    body = auth_client.get(f"/api/v1/ai/results/by-alarm/{ALARM_ID}").json()

    # 同一告警重复触发时，回看应看到最近一条，而不是最旧那条
    assert body["id"] == newest.id
    assert body["confidence"] == pytest.approx(0.93)


def test_by_alarm_is_scoped_to_that_alarm(auth_client, db, created):
    _make(db, created, alarm_id=ALARM_ID, boxes=BOXES, image_path=IMAGE_PATH)
    other = _make(db, created, alarm_id=ALARM_ID + 1, boxes=BOXES, image_path=IMAGE_PATH)

    body = auth_client.get(f"/api/v1/ai/results/by-alarm/{ALARM_ID}").json()

    assert body["id"] != other.id
    assert body["alarm_id"] == ALARM_ID


def test_by_alarm_404_when_no_linked_result(auth_client, db):
    missing = 987654
    # 先确认真的没有关联行，否则 404 断言会因为脏数据假过
    assert db.query(AiResult).filter(AiResult.alarm_id == missing).count() == 0

    r = auth_client.get(f"/api/v1/ai/results/by-alarm/{missing}")

    assert r.status_code == 404, r.text
    assert r.json()["code"] == "NOT_FOUND"
    assert "没有关联" in r.json()["message"]
