from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.ai import AiResult
from app.models.alarm import AlarmRecord
from app.models.inspection import WorkOrder
from app.services.alarm_retention import purge_old_alarms


def test_purge_keeps_workorder_alarm_and_deletes_image(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    old = datetime.now() - timedelta(days=40)
    new = datetime.now() - timedelta(days=1)
    img = tmp_path / "old.jpg"
    img.write_bytes(b"x")

    with Session(engine) as db:
        a_old = AlarmRecord(metric="ai_a", level="warn", message="old", started_at=old)
        a_wo = AlarmRecord(metric="ai_b", level="critical", message="wo", started_at=old)
        a_new = AlarmRecord(metric="ai_c", level="warn", message="new", started_at=new)
        db.add_all([a_old, a_wo, a_new])
        db.flush()
        db.add(WorkOrder(title="工单", source="alarm", source_id=a_wo.id))
        db.add_all([
            AiResult(source_id=1, external_event_id="e1", algorithm="a", confidence=0.9,
                     ts=old, alarm_id=a_old.id, image_path=str(img)),
            AiResult(source_id=1, external_event_id="e2", algorithm="a", confidence=0.9,
                     ts=new, alarm_id=a_new.id),
        ])
        db.commit()

        out = purge_old_alarms(db, keep_days=30, image_root=tmp_path)
        db.commit()

        assert out["ai_results"] == 1
        assert out["images"] == 1
        assert out["alarms"] == 1
        assert not img.exists()
        assert db.get(AlarmRecord, a_old.id) is None
        assert db.get(AlarmRecord, a_wo.id) is not None   # 已转工单，保留
        assert db.get(AlarmRecord, a_new.id) is not None
