"""AI 识别结果 → 平台告警（P1/P2 分级 + 置信度阈值 + 60s 去重）。

规则口径（现场/评审确认）：
- 只有机器人自带相机（external_camera_id 12 dog / 13 dog-云台 / 14 室外）
  的识别结果才建告警，普通固定相机的误报不该进告警中心；
- P1（火焰/烟雾/行人闯入/消防通道堵塞）→ critical，置信度 ≥0.5；
- P2（安全帽/安全着装/工作服/反光衣/吸烟/摔倒/人员离岗）→ warn，置信度 ≥0.4；
- 其他算法（车辆违停/人员计数/玩手机/车牌…）不告警；
- 同一 (external_camera_id, algorithm) 60s 内只建一条，避免一次闯入刷出几十条。

`evaluate(db, result)` 收 `now`/`store` 两个注入点：时间可注入才能测 60/61 秒
去重，store 可注入才能把"是否调用 raise_external、参数对不对"和数据库解耦。
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
from app.services.ai_callback_ingest import ingest

ROBOT_CAMERA = 13
CAMERA_NAME = "dog-云台"


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


class FakeStore:
    """记录调用参数的假 AlarmStore：只验证"要不要建、建成什么级别/消息"。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._next_id = 1

    def raise_external(self, **kwargs) -> SimpleNamespace:
        self.calls.append(kwargs)
        alarm = SimpleNamespace(id=self._next_id, **kwargs)
        self._next_id += 1
        return alarm


@pytest.fixture
def store():
    return FakeStore()


@pytest.fixture
def result_factory(db):
    ids: list[int] = []

    def make(**overrides) -> AiResult:
        fields = {
            "source_id": 1,
            "external_event_id": f"test-{uuid.uuid4().hex}",
            "algorithm": "行人闯入",
            "external_camera_id": ROBOT_CAMERA,
            "external_camera_name": CAMERA_NAME,
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


# ---------- 1. 分级与阈值 ----------


@pytest.mark.parametrize("algorithm", [
    "火焰识别",
    "烟雾检测",
    "行人闯入",
    "消防通道堵塞识别",
])
def test_p1_algorithms_raise_critical(db, store, result_factory, algorithm):
    row = result_factory(algorithm=algorithm, confidence=0.5)   # 阈值边界含等于

    alarm = evaluate(db, row, now=1000.0, store=store)

    assert alarm is not None
    assert alarm.level == "critical"
    assert alarm.metric == f"ai_{algorithm}"
    assert alarm.value == pytest.approx(0.5)
    assert alarm.robot_id == 2
    assert alarm.camera_id is None
    assert len(store.calls) == 1


@pytest.mark.parametrize("algorithm", [
    "安全帽(安全帽/鸭舌帽/棉帽)识别",
    "安全着装【工作服R】",
    "工作服识别",
    "反光衣识别",
    "吸烟识别",
    "摔倒检测",
    "人员离岗",
])
def test_p2_algorithms_raise_warn(db, store, result_factory, algorithm):
    row = result_factory(algorithm=algorithm, confidence=0.4)   # 阈值边界含等于

    alarm = evaluate(db, row, now=1000.0, store=store)

    assert alarm is not None
    assert alarm.level == "warn"
    assert alarm.metric == f"ai_{algorithm}"
    assert len(store.calls) == 1


@pytest.mark.parametrize(("algorithm", "confidence"), [
    ("火焰识别", 0.49),
    ("行人闯入", 0.499),
    ("安全帽识别", 0.399),
    ("吸烟识别", 0.0),
])
def test_low_confidence_is_ignored(db, store, result_factory, algorithm, confidence):
    row = result_factory(algorithm=algorithm, confidence=confidence)

    assert evaluate(db, row, now=1000.0, store=store) is None
    assert store.calls == []
    assert row.alarm_id is None


# ---------- 2. 相机范围 ----------


@pytest.mark.parametrize("camera_id", [11, 15, 99, None])
def test_non_robot_camera_is_ignored(db, store, result_factory, camera_id):
    row = result_factory(external_camera_id=camera_id, algorithm="火焰识别",
                         confidence=0.99)

    assert evaluate(db, row, now=1000.0, store=store) is None
    assert store.calls == []


def test_robot_camera_ids_can_be_overridden_by_env(db, store, result_factory, monkeypatch):
    monkeypatch.setenv("AI_ROBOT_CAMERA_IDS", "12, 13")

    inside = result_factory(external_camera_id=13, algorithm="火焰识别", confidence=0.99)
    outside = result_factory(external_camera_id=14, algorithm="烟雾识别", confidence=0.99)

    assert evaluate(db, inside, now=1000.0, store=store) is not None
    assert evaluate(db, outside, now=1000.0, store=store) is None
    assert len(store.calls) == 1


# ---------- 3. 其他算法不告警 ----------


@pytest.mark.parametrize("algorithm", [
    "车辆违停",
    "人员计数",
    "玩手机识别",
    "车牌识别",
    "区域入侵",     # 名字像安全类，但不在本轮的 P1/P2 清单里
])
def test_other_algorithms_are_ignored(db, store, result_factory, algorithm):
    row = result_factory(algorithm=algorithm, confidence=0.99)

    assert evaluate(db, row, now=1000.0, store=store) is None
    assert store.calls == []


# ---------- 4. 去重 ----------


def test_same_camera_and_algorithm_deduped_within_60s(db, store, result_factory):
    first = result_factory(algorithm="行人闯入", confidence=0.9)
    second = result_factory(algorithm="行人闯入", confidence=0.95)

    assert evaluate(db, first, now=1000.0, store=store) is not None
    assert evaluate(db, second, now=1059.9, store=store) is None
    assert len(store.calls) == 1


def test_same_camera_and_algorithm_allowed_after_61s(db, store, result_factory):
    first = result_factory(algorithm="行人闯入", confidence=0.9)
    second = result_factory(algorithm="行人闯入", confidence=0.9)

    assert evaluate(db, first, now=1000.0, store=store) is not None
    assert evaluate(db, second, now=1061.0, store=store) is not None
    assert len(store.calls) == 2


def test_different_algorithm_is_not_deduped(db, store, result_factory):
    fire = result_factory(algorithm="火焰识别", confidence=0.9)
    smoke = result_factory(algorithm="烟雾识别", confidence=0.9)

    assert evaluate(db, fire, now=1000.0, store=store) is not None
    assert evaluate(db, smoke, now=1000.0, store=store) is not None
    assert len(store.calls) == 2


# ---------- 5. 调用契约与写回 ----------


def test_message_and_raise_external_arguments(db, store, result_factory):
    row = result_factory(algorithm="行人闯入", confidence=0.917047)

    alarm = evaluate(db, row, now=1000.0, store=store)

    assert alarm is not None
    call = store.calls[0]
    assert call["metric"] == "ai_行人闯入"
    assert call["level"] == "critical"
    assert call["message"] == "dog-云台 检测到 行人闯入（置信度 0.92）"
    assert call["value"] == pytest.approx(0.917047)
    assert call["camera_id"] is None
    assert call["robot_id"] == 2
    assert set(call) == {"metric", "level", "message", "value", "camera_id", "robot_id"}


def test_missing_camera_name_falls_back_to_id(db, store, result_factory):
    row = result_factory(algorithm="烟雾识别", external_camera_name=None, confidence=0.8)

    assert evaluate(db, row, now=1000.0, store=store) is not None
    assert store.calls[0]["message"].startswith("摄像头13 检测到 烟雾识别")


def test_alarm_id_is_written_back_to_result(db, store, result_factory):
    row = result_factory(algorithm="行人闯入", confidence=0.9)

    alarm = evaluate(db, row, now=1000.0, store=store)

    assert alarm is not None
    db.expire_all()
    saved = db.get(AiResult, row.id)
    assert saved.alarm_id == alarm.id
    assert saved.alarm_id == 1


def test_no_store_means_no_alarm_and_no_crash(db, result_factory, monkeypatch):
    monkeypatch.setattr(ai_alarm.alarms, "get_store", lambda: None)
    row = result_factory(algorithm="行人闯入", confidence=0.9)

    assert evaluate(db, row, now=1000.0) is None


# ---------- 6. 入库后自动评估 ----------


def _body(snowflake_id: int, algorithm: str, *, camera_id: int = ROBOT_CAMERA,
          score: float = 0.9) -> dict:
    return {
        "snowflake_id": snowflake_id,
        "timestamp": "2026-11-18 15:55:34",
        "algorithm_name": algorithm,
        "camera_id": camera_id,
        "camera_name": CAMERA_NAME,
        "result_data": [{
            "result_data": {"task_result": {"object_list": [{"score": score}]}},
        }],
    }


def _new_snowflake() -> int:
    return uuid.uuid4().int % 9_000_000_000_000_000_000


@pytest.fixture
def ingested_rows(db):
    ids: list[int] = []

    def clean() -> None:
        if ids:
            db.query(AiResult).filter(AiResult.id.in_(ids)).delete()
            db.commit()

    yield ids
    clean()


def test_ingest_creates_alarm_and_writes_alarm_id(db, monkeypatch, ingested_rows):
    fake = FakeStore()
    monkeypatch.setattr(ai_alarm.alarms, "get_store", lambda: fake)
    snowflake = _new_snowflake()

    out = ingest(db, _body(snowflake, "行人闯入", score=0.93))
    ingested_rows.append(out["result_id"])

    assert out["ingested"] is True
    assert len(fake.calls) == 1
    assert fake.calls[0]["level"] == "critical"
    db.expire_all()
    assert db.get(AiResult, out["result_id"]).alarm_id == 1


def test_ingest_survives_alarm_failure(db, monkeypatch, ingested_rows):
    def boom(*args, **kwargs):  # noqa: ANN001
        raise RuntimeError("alarm store down")

    monkeypatch.setattr(ai_alarm, "evaluate", boom)
    snowflake = _new_snowflake()

    out = ingest(db, _body(snowflake, "行人闯入"))

    ingested_rows.append(out["result_id"])
    assert out["ingested"] is True
    db.expire_all()
    assert db.get(AiResult, out["result_id"]).alarm_id is None
