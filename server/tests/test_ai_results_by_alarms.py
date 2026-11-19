"""告警列表批量缩略图：GET /ai/results/by-alarms?alarm_ids=1,2,3。

列表页每行 AI 告警都要一张 60×44 缩略图，逐行调 by-alarm/{id} 会把首屏打成
N 个请求，所以有这条批量接口。锁四件事：

1. 多个 id 一次返回，按 alarm_id 分组；
2. 每条告警只取 id 最大（最新）的那条结果——缩略图必须对应最近证据；
3. 不存在的 id 静默忽略，不能让整页 404；
4. 超过 100 个 id 必须被截断（或明确 400），不能把整库查出来。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

import pytest

from app.db.init import create_all
from app.db.session import SessionLocal
from app.models.ai import AiResult

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


def _make(db, ids: list[int], *, alarm_id: int, confidence: float = 0.8,
          boxes: list[dict] | None = None, image_path: str | None = IMAGE_PATH) -> AiResult:
    row = AiResult(
        source_id=1,
        external_event_id=uuid.uuid4().hex,
        algorithm="行人闯入",
        external_camera_id=12,
        external_camera_name="dog",
        external_algorithm_id=101,
        confidence=confidence,
        ts=datetime.now().replace(microsecond=0),
        boxes_json=json.dumps(boxes if boxes is not None else BOXES, ensure_ascii=False),
        image_path=image_path,
        alarm_id=alarm_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    ids.append(row.id)
    return row


def _get(auth_client, ids: list[int] | str):
    raw = ids if isinstance(ids, str) else ",".join(str(i) for i in ids)
    return auth_client.get("/api/v1/ai/results/by-alarms", params={"alarm_ids": raw})


def test_returns_items_grouped_by_alarm_id(auth_client, db, created):
    a = _make(db, created, alarm_id=7101, confidence=0.71)
    b = _make(db, created, alarm_id=7102, confidence=0.82)
    c = _make(db, created, alarm_id=7103, confidence=0.93)

    r = _get(auth_client, [7101, 7102, 7103])

    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert set(items) == {"7101", "7102", "7103"}
    assert items["7101"]["id"] == a.id
    assert items["7102"]["id"] == b.id
    assert items["7103"]["id"] == c.id
    # 缩略图/大图面板都靠这两个字段，批量接口不能省
    assert items["7101"]["image"] == f"/api/v1/ai/results/{a.id}/image"
    assert items["7101"]["boxes"] == BOXES


def test_returns_latest_result_per_alarm(auth_client, db, created):
    _make(db, created, alarm_id=7200, confidence=0.50)
    newest = _make(db, created, alarm_id=7200, confidence=0.95)

    items = _get(auth_client, [7200]).json()["items"]

    assert items["7200"]["id"] == newest.id
    assert items["7200"]["confidence"] == pytest.approx(0.95)


def test_missing_alarm_ids_are_ignored(auth_client, db, created):
    row = _make(db, created, alarm_id=7300)

    r = _get(auth_client, [7300, 999998, 999999])

    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert list(items) == ["7300"]
    assert items["7300"]["id"] == row.id


def test_more_than_100_ids_is_truncated_or_rejected(auth_client, db, created):
    ids = list(range(7400, 7501))
    for aid in ids:
        _make(db, created, alarm_id=aid)

    r = _get(auth_client, ids)

    if r.status_code == 400:
        assert "100" in r.json()["message"]
    else:
        assert r.status_code == 200, r.text
        assert len(r.json()["items"]) == 100


def test_empty_or_garbage_ids_return_empty(auth_client):
    assert _get(auth_client, "").json() == {"items": {}}
    assert _get(auth_client, "abc,,-3").json() == {"items": {}}
