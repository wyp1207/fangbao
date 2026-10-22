"""用户管理：仅 admin 可用的账号 CRUD。

设计要点：
- 不暴露 password_hash；任何响应里都没有密码字段。
- 不允许删/停用自己，避免把最后一个管理员锁在门外。
- 改密码走单独接口，不需要旧密码（这是管理员重置，不是用户自助改密）。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_csrf, require_roles
from app.core.errors import BadRequest, NotFound
from app.core.security import hash_password, validate_password
from app.db.session import get_db
from app.models.user import User
from app.services.messages import audit, store as msg_store

router = APIRouter(prefix="/users", tags=["users"])

ROLES = ("admin", "sysadmin", "secadmin", "auditor", "safety", "operator", "viewer")

# 三权分立：系统管理员管账号/设备/密钥；安全管理员管安全策略；
# 审计管理员只能看审计，不能改任何东西。admin 是过渡超级角色（保留兼容）。
ROLE_LABELS = {
    "admin": "超级管理员（过渡）",
    "sysadmin": "系统管理员",
    "secadmin": "安全管理员",
    "auditor": "审计管理员",
    "safety": "安全员",
    "operator": "操作员",
    "viewer": "只读",
}


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    role_label: str | None = None
    is_active: bool
    must_change_password: bool = False
    created_at: datetime | None = None
    last_login_at: datetime | None = None


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    role: str = "operator"


class UserUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=6, max_length=128)


def _out(u: User) -> UserOut:
    return UserOut(
        id=u.id, username=u.username, role=u.role,
        role_label=ROLE_LABELS.get(u.role, u.role), is_active=u.is_active,
        created_at=u.created_at, last_login_at=u.last_login_at,
        must_change_password=bool(u.must_change_password),
    )


def _check_role(role: str) -> None:
    if role not in ROLES:
        raise BadRequest(f"角色只能是 {'/'.join(ROLES)}", code="BAD_ROLE")


@router.get("", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "sysadmin")),
) -> list[UserOut]:
    rows = db.scalars(select(User).order_by(User.id)).all()
    return [_out(u) for u in rows]


@router.post("", response_model=UserOut, dependencies=[Depends(require_csrf)])
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "sysadmin")),
) -> UserOut:
    _check_role(body.role)
    if db.scalar(select(User).where(User.username == body.username)):
        raise BadRequest("用户名已存在", code="USERNAME_TAKEN")
    try:
        validate_password(body.password, username=body.username)
    except ValueError as exc:
        raise BadRequest(str(exc), code="WEAK_PASSWORD") from exc

    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        must_change_password=True,        # 初始密码必须改掉
        role=body.role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    from app.models.user import PasswordHistory
    db.add(PasswordHistory(user_id=user.id, password_hash=user.password_hash))
    user.password_changed_at = datetime.now()
    db.commit()
    db.refresh(user)
    msg_store.add("info", "user", f"新建账号：{user.username}",
                  f"角色 {user.role}", {"to": "users"})
    audit(db=db, action="user.create", target=user.username, user=me,
          detail={"role": user.role}, summary=f"角色 {user.role}")
    return _out(user)


@router.patch("/{user_id}", response_model=UserOut, dependencies=[Depends(require_csrf)])
def update_user(
    user_id: int,
    body: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "sysadmin")),
) -> UserOut:
    user = db.get(User, user_id)
    if not user:
        raise NotFound("用户不存在")
    if body.role is not None:
        _check_role(body.role)
        user.role = body.role
    if body.is_active is not None:
        if user.id == me.id and not body.is_active:
            raise BadRequest("不能停用自己的账号", code="SELF_DISABLE")
        user.is_active = body.is_active
    db.commit()
    db.refresh(user)
    msg_store.add("info", "user", f"修改账号：{user.username}",
                  f"角色 {user.role} / {'启用' if user.is_active else '停用'}", {"to": "users"})
    audit(db=db, action="user.update", target=user.username, user=me,
          detail={"role": user.role, "active": user.is_active})
    return _out(user)


@router.post("/{user_id}/password", dependencies=[Depends(require_csrf)])
def reset_password(
    user_id: int,
    body: PasswordReset,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "sysadmin")),
) -> dict:
    user = db.get(User, user_id)
    if not user:
        raise NotFound("用户不存在")
    try:
        validate_password(body.password, username=user.username)
    except ValueError as exc:
        raise BadRequest(str(exc), code="WEAK_PASSWORD") from exc
    user.password_hash = hash_password(body.password)
    user.must_change_password = True      # 重置后强制改密
    user.password_changed_at = datetime.now()
    from app.models.user import PasswordHistory
    db.add(PasswordHistory(user_id=user.id, password_hash=user.password_hash))
    db.commit()
    msg_store.add("warn", "user", f"管理员重置密码：{user.username}",
                  f"操作人 {me.username}", {"to": "users"})
    audit(db=db, action="user.password", target=user.username, user=me,
          summary="管理员重置密码")
    return {"ok": True}


@router.delete("/{user_id}", dependencies=[Depends(require_csrf)])
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles("admin", "sysadmin")),
) -> dict:
    user = db.get(User, user_id)
    if not user:
        raise NotFound("用户不存在")
    if user.id == me.id:
        raise BadRequest("不能删除自己的账号", code="SELF_DELETE")
    admins = db.scalars(select(User).where(User.role == "admin", User.is_active.is_(True))).all()
    if user.role == "admin" and len(admins) <= 1:
        raise BadRequest("至少要保留一个管理员", code="LAST_ADMIN")
    db.delete(user)
    db.commit()
    msg_store.add("warn", "user", f"删除账号：{user.username}",
                  f"操作人 {me.username}", {"to": "users"})
    audit(db=db, action="user.delete", target=user.username, user=me,
          summary="删除账号")
    return {"ok": True}
