"""设备接入凭证：一机一密 + HMAC 签名 + 防重放。

为什么要有：设备上报口（/task-runs/ingest 等）原来只认平台 API Key，
一台设备的 key 泄露就能伪造任意设备上报；评估里"设备侧无认证"是硬伤。

签名规则（设备端实现同样四行）：
    body_hash = sha256(raw_body).hexdigest()
    msg       = f"{key_id}\n{timestamp}\n{nonce}\n{body_hash}"
    signature = hex(hmac_sha256(secret, msg))
请求头：X-Device-Key / X-Timestamp / X-Nonce / X-Signature
窗口 ±300 秒；同一个 (key, nonce) 只能用一次（DB 唯一索引挡住重放）。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import seal, unseal
from app.models.device_credential import DeviceCredential, DeviceNonce

log = logging.getLogger(__name__)

WINDOW_S = 300
NONCE_TTL_S = 900


def _body_hash(body: bytes) -> str:
    return hashlib.sha256(body or b"").hexdigest()


def sign(secret: str, key_id: str, ts: int, nonce: str, body: bytes) -> str:
    msg = "%s\n%s\n%s\n%s" % (key_id, ts, nonce, _body_hash(body))
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


def issue(db: Session, robot_id: int, *, secret: str) -> tuple[DeviceCredential, str]:
    """签发或轮换凭证；返回（记录，明文密钥）。明文只返回这一次。"""
    cred = db.scalar(select(DeviceCredential).where(DeviceCredential.robot_id == robot_id))
    raw = secrets.token_urlsafe(24)
    if cred is None:
        cred = DeviceCredential(
            robot_id=robot_id,
            key_id="dev_%d_%s" % (robot_id, secrets.token_hex(4)),
            secret_enc=seal(raw, secret=secret),
            enabled=True,
            created_at=datetime.now(),
        )
        db.add(cred)
    else:
        cred.key_id = "dev_%d_%s" % (robot_id, secrets.token_hex(4))
        cred.secret_enc = seal(raw, secret=secret)
        cred.enabled = True
        cred.revoked_at = None
        cred.created_at = datetime.now()
    db.commit()
    db.refresh(cred)
    return cred, raw


def revoke(db: Session, cred_id: int) -> bool:
    cred = db.get(DeviceCredential, cred_id)
    if cred is None:
        return False
    cred.enabled = False
    cred.revoked_at = datetime.now()
    db.commit()
    return True


def credential_for(db: Session, robot_id: int) -> DeviceCredential | None:
    return db.scalar(select(DeviceCredential).where(DeviceCredential.robot_id == robot_id))


def verify(db: Session, *, key_id: str, ts: str, nonce: str, signature: str,
           body: bytes, secret: str) -> tuple[bool, str]:
    cred = db.scalar(select(DeviceCredential).where(DeviceCredential.key_id == key_id))
    if cred is None or not cred.enabled:
        return False, "凭证不存在或已吊销"
    try:
        ts_i = int(ts)
    except (TypeError, ValueError):
        return False, "时间戳非法"
    if abs(int(datetime.now().timestamp()) - ts_i) > WINDOW_S:
        return False, "时间戳超出 ±%d 秒（防重放）" % WINDOW_S
    real = sign(unseal(cred.secret_enc, secret=secret), key_id, ts_i, nonce, body)
    if not hmac.compare_digest(real, signature or ""):
        return False, "签名不匹配"
    if not nonce or len(nonce) > 64:
        return False, "nonce 非法"
    db.add(DeviceNonce(key_id=key_id, nonce=nonce, ts=ts_i, created_at=datetime.now()))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False, "nonce 已用过（重放）"
    cred.last_used_at = datetime.now()
    db.commit()
    return True, ""


def purge_nonces(db: Session, older_than_s: int = NONCE_TTL_S) -> int:
    cutoff = datetime.now().timestamp() - older_than_s
    rows = db.query(DeviceNonce).filter(DeviceNonce.ts < int(cutoff)).delete()
    db.commit()
    return rows
