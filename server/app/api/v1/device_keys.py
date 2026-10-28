"""设备接入凭证 API：签发/轮换/吊销（只给管理员）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_csrf, require_roles
from app.core.config import get_settings
from app.core.errors import BadRequest, NotFound
from app.db.session import get_db
from app.models.device_credential import DeviceCredential
from app.models.robot import Robot
from app.models.user import User
from app.services import device_auth
from app.services.messages import audit

router = APIRouter(prefix="/device-keys", tags=["device-keys"])


def _out(c: DeviceCredential) -> dict:
    return {
        "id": c.id, "robot_id": c.robot_id, "key_id": c.key_id,
        "enabled": c.enabled,
        "created_at": c.created_at.isoformat(timespec="seconds") if c.created_at else None,
        "last_used_at": c.last_used_at.isoformat(timespec="seconds") if c.last_used_at else None,
        "revoked_at": c.revoked_at.isoformat(timespec="seconds") if c.revoked_at else None,
    }


@router.get("")
def list_keys(db: Session = Depends(get_db),
              _: User = Depends(require_roles("admin", "safety"))) -> list[dict]:
    return [_out(c) for c in db.query(DeviceCredential).order_by(DeviceCredential.id).all()]


@router.post("", dependencies=[Depends(require_csrf)])
def issue_key(body: dict, db: Session = Depends(get_db),
              me: User = Depends(require_roles("admin"))) -> dict:
    """给某台设备签发/轮换密钥；明文只返回这一次。"""
    robot_id = int(body.get("robot_id") or 0)
    robot = db.get(Robot, robot_id)
    if robot is None:
        raise BadRequest("设备不存在", code="NO_ROBOT")
    cred, secret = device_auth.issue(db, robot_id, secret=get_settings().secret_key)
    audit(db=db, action="device_key.issue", target=robot.name, user=me,
          detail={"robot_id": robot_id, "key_id": cred.key_id})
    return {**_out(cred), "secret": secret,
            "sign_rule": "sha256(body) → hmac_sha256(secret, key_id\\ntimestamp\\nnonce\\nbody_hash)"}


@router.post("/{cred_id}/revoke", dependencies=[Depends(require_csrf)])
def revoke_key(cred_id: int, db: Session = Depends(get_db),
               me: User = Depends(require_roles("admin"))) -> dict:
    cred = db.get(DeviceCredential, cred_id)
    if cred is None:
        raise NotFound("凭证不存在")
    device_auth.revoke(db, cred_id)
    audit(db=db, action="device_key.revoke", target=cred.key_id, user=me,
          detail={"robot_id": cred.robot_id})
    return {"ok": True, "id": cred_id, "enabled": False}
