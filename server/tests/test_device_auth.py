"""设备一机一密：签名正确/错误/过期/重放/吊销 与 ingest 端到端。"""

from __future__ import annotations

import json
import time
import uuid

from app.core.config import get_settings
from app.db.session import Base, SessionLocal, engine
from app.models.device_credential import DeviceCredential, DeviceNonce  # noqa: F401
from app.services import device_auth

ROBOT = 1


def _ensure():
    Base.metadata.create_all(bind=engine)


def _clean(robot_id: int = ROBOT):
    with SessionLocal() as db:
        db.query(DeviceNonce).delete()
        db.query(DeviceCredential).filter(DeviceCredential.robot_id == robot_id).delete()
        db.commit()


def test_signature_roundtrip():
    _ensure()
    _clean()
    with SessionLocal() as db:
        cred, raw = device_auth.issue(db, ROBOT, secret=get_settings().secret_key)
        body = json.dumps({"external_id": "x", "robot_id": ROBOT}).encode()
        ts = int(time.time())
        nonce = uuid.uuid4().hex
        sig = device_auth.sign(raw, cred.key_id, ts, nonce, body)
        ok, why = device_auth.verify(db, key_id=cred.key_id, ts=str(ts), nonce=nonce,
                                     signature=sig, body=body,
                                     secret=get_settings().secret_key)
        assert ok, why
    _clean()


def test_bad_signature_rejected():
    _ensure()
    _clean()
    with SessionLocal() as db:
        cred, raw = device_auth.issue(db, ROBOT, secret=get_settings().secret_key)
        ok, why = device_auth.verify(db, key_id=cred.key_id, ts=str(int(time.time())),
                                     nonce=uuid.uuid4().hex, signature="deadbeef",
                                     body=b"{}", secret=get_settings().secret_key)
        assert not ok and "签名" in why
    _clean()


def test_stale_timestamp_rejected():
    _ensure()
    _clean()
    with SessionLocal() as db:
        cred, raw = device_auth.issue(db, ROBOT, secret=get_settings().secret_key)
        ts = int(time.time()) - 3600
        nonce = uuid.uuid4().hex
        sig = device_auth.sign(raw, cred.key_id, ts, nonce, b"{}")
        ok, why = device_auth.verify(db, key_id=cred.key_id, ts=str(ts), nonce=nonce,
                                     signature=sig, body=b"{}",
                                     secret=get_settings().secret_key)
        assert not ok and "时间戳" in why
    _clean()


def test_replay_rejected():
    _ensure()
    _clean()
    with SessionLocal() as db:
        cred, raw = device_auth.issue(db, ROBOT, secret=get_settings().secret_key)
        body = b"{}"
        ts = int(time.time())
        nonce = uuid.uuid4().hex
        sig = device_auth.sign(raw, cred.key_id, ts, nonce, body)
        first, _ = device_auth.verify(db, key_id=cred.key_id, ts=str(ts), nonce=nonce,
                                      signature=sig, body=body,
                                      secret=get_settings().secret_key)
        second, why = device_auth.verify(db, key_id=cred.key_id, ts=str(ts), nonce=nonce,
                                         signature=sig, body=body,
                                         secret=get_settings().secret_key)
        assert first is True and second is False and "重放" in why
    _clean()


def test_revoked_key_rejected():
    _ensure()
    _clean()
    with SessionLocal() as db:
        cred, raw = device_auth.issue(db, ROBOT, secret=get_settings().secret_key)
        device_auth.revoke(db, cred.id)
        ok, why = device_auth.verify(db, key_id=cred.key_id, ts=str(int(time.time())),
                                     nonce=uuid.uuid4().hex, signature="x", body=b"{}",
                                     secret=get_settings().secret_key)
        assert not ok and "吊销" in why
    _clean()


def test_ingest_signed_ok_and_unsigned_rejected(auth_client):
    import os

    os.environ["JC_DEVICE_AUTH_MODE"] = "strict"
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _ensure()
    _clean()
    try:
        issue = auth_client.post("/api/v1/device-keys", json={"robot_id": ROBOT})
        assert issue.status_code == 200, issue.text
        cred = issue.json()

        # 模拟"没有平台会话的设备"：清掉管理员 cookie，再试无签名上报
        auth_client.cookies.clear()

        payload = {"external_id": "DEV-%d" % int(time.time()), "status": "done",
                   "robot_id": ROBOT, "steps": [{"seq": 1, "point_name": "P1", "status": "ok"}]}
        body = json.dumps(payload).encode()

        r1 = auth_client.post("/api/v1/task-runs/ingest", content=body,
                              headers={"Content-Type": "application/json"})
        assert r1.status_code == 401, r1.text

        ts = str(int(time.time()))
        nonce = uuid.uuid4().hex
        sig = device_auth.sign(cred["secret"], cred["key_id"], int(ts), nonce, body)
        r2 = auth_client.post("/api/v1/task-runs/ingest", content=body, headers={
            "Content-Type": "application/json",
            "X-Device-Key": cred["key_id"], "X-Timestamp": ts,
            "X-Nonce": nonce, "X-Signature": sig,
        })
        assert r2.status_code == 200, r2.text
        assert r2.json()["created"] is True
    finally:
        os.environ.pop("JC_DEVICE_AUTH_MODE", None)
        get_settings.cache_clear()  # type: ignore[attr-defined]
        _clean()
