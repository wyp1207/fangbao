"""告警推导的最小检查：不用阈值也要判出来的那几条。"""

from app.services.alarms import AlarmStore

GOOD_INFO = {"battery": 78, "driver_port": False}


def test_no_alarm_when_everything_fine():
    store = AlarmStore()
    assert store.evaluate(status={"status": "Free"}, info=GOOD_INFO, age_s=0.2) == []
    assert store.list() == []


def test_low_battery_warn_then_critical():
    store = AlarmStore()
    warn = store.evaluate(status={}, info={"battery": 15, "driver_port": False}, age_s=0)
    assert [a.metric for a in warn] == ["battery"]
    assert warn[0].level == "warn"

    fresh = AlarmStore()  # 全新 store，避开去重窗口
    crit = fresh.evaluate(status={}, info={"battery": 8, "driver_port": False}, age_s=0)
    assert crit[0].level == "critical"


def test_estop_alarm():
    store = AlarmStore()
    alarms = store.evaluate(status={}, info={"battery": 80, "driver_port": True}, age_s=0)
    assert [a.metric for a in alarms] == ["estop"]
    assert alarms[0].level == "critical"


def test_offline_after_threshold():
    store = AlarmStore()
    assert store.evaluate(status={}, info={}, age_s=3) == []
    got = store.evaluate(status={}, info={}, age_s=30)
    assert [a.metric for a in got] == ["offline"]


def test_dedupe_within_window():
    store = AlarmStore(dedupe_s=60)
    assert len(store.evaluate(status={}, info={"battery": 5, "driver_port": False}, age_s=0)) == 1
    assert store.evaluate(status={}, info={"battery": 5, "driver_port": False}, age_s=0) == []


def test_ack_sets_who_and_time():
    store = AlarmStore()
    alarm = store.evaluate(status={}, info={"battery": 5, "driver_port": False}, age_s=0)[0]
    acked = store.ack(alarm.id, who="admin")
    assert acked["acked_by"] == "admin"
    assert acked["acked_at"]
    assert store.list(active_only=True) == []


def test_ack_unknown_id_returns_none():
    assert AlarmStore().ack(999, who="admin") is None


def test_latest_first():
    store = AlarmStore(dedupe_s=0)
    store.evaluate(status={}, info={"battery": 5, "driver_port": False}, age_s=0)
    store.evaluate(status={}, info={"battery": 80, "driver_port": True}, age_s=0)
    metrics = [a["metric"] for a in store.list()]
    assert metrics[0] == "estop" and metrics[-1] == "battery"
