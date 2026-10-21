from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.errors import Unauthorized
from app.core.security import create_access_token, new_csrf_token, verify_password
from app.db.session import get_db
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    role: str


class LoginOut(BaseModel):
    user: UserOut
    csrf_token: str


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)) -> LoginOut:
    settings = get_settings()
    user = db.scalar(select(User).where(User.username == body.username))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise Unauthorized("用户名或密码错误")

    token = create_access_token(
        str(user.id), user.role, secret=settings.secret_key,
        ttl_minutes=settings.jwt_ttl_minutes,
    )
    csrf = new_csrf_token()
    secure = not settings.is_dev
    response.set_cookie(
        settings.cookie_name, token, httponly=True, samesite="lax",
        secure=secure, max_age=settings.jwt_ttl_minutes * 60, path="/",
    )
    response.set_cookie(
        settings.csrf_cookie, csrf, httponly=False, samesite="lax",
        secure=secure, max_age=settings.jwt_ttl_minutes * 60, path="/",
    )
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return LoginOut(user=UserOut(id=user.id, username=user.username, role=user.role),
                    csrf_token=csrf)


@router.post("/logout")
def logout(response: Response) -> dict:
    settings = get_settings()
    response.delete_cookie(settings.cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(id=user.id, username=user.username, role=user.role)
