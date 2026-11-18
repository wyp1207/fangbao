"""同一算法从不同机器人相机进来 → 各自独立告警，不能被按 metric 吞掉。

现场：一台机器狗挂 12(dog)、13(dog-云台)、14(室外) 三路相机，同一个算法在
不同相机上各自成立时是三个独立的现场事实，值班要能看到三条。

`ai_alarm.evaluate` 本来就按 `(external_camera_id, algorithm)` 做 60s 去重，
但真正落库的是 `AlarmStore.raise_external`，它只按 `metric` 去重，而 ai 告警的
metric 是 `ai_{algorithm}`（告警中心口径要求保持不变）——于是第二台相机在同一
个去重窗口里被静默吞掉。这里用**真实 AlarmStore**（不 attach_db，内存模式，
去重逻辑与线上一致）同时验证两层：evaluate 的相机维度窗口 + store 的 dedupe_key。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.db.init import create_all
from app.db.session import SessionLocal
from app.models.ai import AiResult
from app.services import ai_alarm
from app.services.ai_alarm import evaluate
from app.services.alarms import AlarmStore

ALGORITHM = "行人闯入"
CAMERA_DOG = 12
CAMERA_PTZ = 13


@pytest.fixture(scope="module", autouse=True)
def _schema():
    create_all()


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """每个用例都从空的去重窗口开始；env 覆盖不能串用例。"""
    monkeypatch.setattr(ai_alarm, "_last_raised", {})
    monkeypatch.delenv("AI_ROBOT_CAMERA_IDS", raising=False)


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def store():
    """真实 AlarmStore，未 attach_db：去重/建告警逻辑与线上一致，只留在内存。"""
    return AlarmStore()


class FakeStore:
    """只记录调用参数的假 store：验证 evaluate 把哪个 dedupe_key 传下去。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._next_id = 1

    def raise_external(self, **kwargs) -> SimpleNamespace:
        self.calls.append(kwargs)
        alarm = SimpleNamespace(id=self._next_id, **kwargs)
        self._next_id += 1
        return alarm


@pytest.fixture
def result_factory(db):
    ids: list[int] = []

    def make(**overrides) -> AiResult:
        fields = {
            "source_id": 1,
            "external_event_id": f"test-{uuid.uuid4().hex}",
            "algorithm": ALGORITHM,
            "external_camera_id": CAMERA_PTZ,
            "external_camera_name": "dog-云台",
            "confidence": 0.9,
            "ts": datetime.now(),
        }
        fields.update(overrides)
        row = AiResult(**fields)
        db.add(row)
        db.commit()
        db.refresh(row)
        ids.append(row.id)
        return row

    yield make
    if ids:
        db.query(AiResult).filter(AiResult.id.in_(ids)).delete()
        db.commit()


# ---------- 1. 多相机：各自独立告警 ----------


def test_two_cameras_same_algorithm_each_raise_an_alarm(db, store, result_factory):
    """同一算法、camera 13 与 camera 12 间隔 1s → 两条告警，id 不同。"""
    ptz = result_factory(external_camera_id=CAMERA_PTZ, external_camera_name="dog-云台",
                         algorithm=ALGORITHM, confidence=0.9)
    dog = result_factory(external_camera_id=CAMERA_DOG, external_camera_name="dog",
                         algorithm=ALGORITHM, confidence=0.9)

    alarm_ptz = evaluate(db, ptz, now=1000.0, store=store)
    alarm_dog = evaluate(db, dog, now=1001.0, store=store)

    assert alarm_ptz is not None, "camera 13 的告警没建成"
    assert alarm_dog is not None, "camera 12 被按 metric 去重吞掉了"
    assert alarm_ptz.id != alarm_dog.id
    assert ptz.alarm_id == alarm_ptz.id
    assert dog.alarm_id == alarm_dog.id
    assert len(store.list()) == 2


def test_two_cameras_keep_alarm_center_metric_unchanged(db, store, result_factory):
    """告警中心口径不变：两条都还是 `ai_{algorithm}`，消息里能区分相机。"""
    ptz = result_factory(external_camera_id=CAMERA_PTZ, external_camera_name="dog-云台")
    dog = result_factory(external_camera_id=CAMERA_DOG, external_camera_name="dog")

    alarm_ptz = evaluate(db, ptz, now=1000.0, store=store)
    alarm_dog = evaluate(db, dog, now=1001.0, store=store)

    assert alarm_ptz.metric == alarm_dog.metric == f"ai_{ALGORITHM}"
    assert alarm_ptz.message.startswith("dog-云台 检测到")
    assert alarm_dog.message.startswith("dog 检测到")


def test_three_robot_cameras_all_raise_independently(db, store, result_factory):
    """三路机器人相机（12/13/14）同一算法都应各自建告警。"""
    rows = [
        result_factory(external_camera_id=12, external_camera_name="dog"),
        result_factory(external_camera_id=13, external_camera_name="dog-云台"),
        result_factory(external_camera_id=14, external_camera_name="室外"),
    ]

    alarms = [evaluate(db, row, now=1000.0 + i, store=store) for i, row in enumerate(rows)]

    assert all(a is not None for a in alarms)
    assert len({a.id for a in alarms}) == 3
    assert len(store.list()) == 3


# ---------- 2. 同相机同算法仍然去重 ----------


def test_same_camera_and_algorithm_still_deduped_within_60s(db, store, result_factory):
    first = result_factory(external_camera_id=CAMERA_PTZ, algorithm=ALGORITHM,
                           confidence=0.9)
    second = result_factory(external_camera_id=CAMERA_PTZ, algorithm=ALGORITHM,
                            confidence=0.95)

    assert evaluate(db, first, now=1000.0, store=store) is not None
    assert evaluate(db, second, now=1030.0, store=store) is None    # 60s 内
    assert len(store.list()) == 1


# ---------- 3. evaluate → raise_external 的 dedupe_key 契约 ----------


def test_evaluate_passes_camera_scoped_dedupe_key(db, result_factory):
    fake = FakeStore()
    row = result_factory(external_camera_id=CAMERA_PTZ, algorithm=ALGORITHM)

    evaluate(db, row, now=1000.0, store=fake)

    assert fake.calls[0]["dedupe_key"] == f"{CAMERA_PTZ}:{ALGORITHM}"
    assert fake.calls[0]["metric"] == f"ai_{ALGORITHM}"


# ---------- 4. AlarmStore 自身的去重键 ----------


def test_store_dedupes_on_dedupe_key_when_given(store):
    """给了 dedupe_key 就按 key 去重，而不是按 metric。"""
    first = store.raise_external(metric=f"ai_{ALGORITHM}", level="critical",
                                 message="camera 13", dedupe_key=f"{CAMERA_PTZ}:{ALGORITHM}")
    same = store.raise_external(metric=f"ai_{ALGORITHM}", level="critical",
                                message="camera 13 again", dedupe_key=f"{CAMERA_PTZ}:{ALGORITHM}")
    other = store.raise_external(metric=f"ai_{ALGORITHM}", level="critical",
                                 message="camera 12", dedupe_key=f"{CAMERA_DOG}:{ALGORITHM}")

    assert first is not None
    assert same is None
    assert other is not None
    assert first.id != other.id


def test_store_falls_back_to_metric_without_dedupe_key(store):
    """不传 dedupe_key 的来源（磁盘/传感器等）行为不变：仍按 metric 去重。"""
    first = store.raise_external(metric="disk_space", level="warn", message="disk 90%")
    second = store.raise_external(metric="disk_space", level="warn", message="disk 91%")

    assert first is not None
    assert second is None
