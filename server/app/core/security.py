"""密码哈希（stdlib scrypt）、JWT、CSRF。

不引入 passlib/argon2：单人项目少一个依赖少一个坑，scrypt 在标准库里。
ponytail: 峰值只是“没有 argon2 的抗 GPU 优势”，参数已随哈希串存下来，
将来要换算法按前缀 `scrypt$` 分支迁移即可。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DKLEN = 32


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_DKLEN
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(
            password.encode(),
            salt=_unb64(salt_b64),
            n=int(n), r=int(r), p=int(p), dklen=len(_unb64(hash_b64)),
        )
        return hmac.compare_digest(dk, _unb64(hash_b64))
    except Exception:
        return False


def create_access_token(subject: str, role: str, *, secret: str, ttl_minutes: int) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, *, secret: str) -> dict[str, Any]:
    return jwt.decode(token, secret, algorithms=["HS256"])


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def csrf_matches(cookie_value: str | None, header_value: str | None) -> bool:
    if not cookie_value or not header_value:
        return False
    return hmac.compare_digest(cookie_value, header_value)


# ---------- 设备凭据的"封存" ----------
# 说明：这不是强加密。平台要拿原文去连设备，任何本地密钥都能被同机读取，
# 这一层只是避免"数据库里直接看到明文密码"，真正防线是网络隔离与最小权限。
# 用 SHA256(secret|nonce) 做密钥流异或，避免引入 cryptography 依赖。

def seal(plain: str, *, secret: str) -> str:
    import hashlib
    import os

    if not plain:
        return ""
    nonce = os.urandom(16)
    key = hashlib.sha256(secret.encode() + nonce).digest()
    data = plain.encode()
    out = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return _b64(nonce + out)


def unseal(blob: str, *, secret: str) -> str:
    import hashlib

    if not blob:
        return ""
    try:
        raw = _unb64(blob)
        nonce, data = raw[:16], raw[16:]
        key = hashlib.sha256(secret.encode() + nonce).digest()
        return bytes(b ^ key[i % len(key)] for i, b in enumerate(data)).decode()
    except Exception:  # noqa: BLE001
        return ""


# ---------- 密码策略 ----------
MIN_PASSWORD_LEN = 8


def validate_password(password: str, *, username: str = "") -> None:
    """密码强度：≥8 位、含字母和数字、不能等于用户名。

    抛 ValueError（由调用方转成 400），不在这里引 FastAPI 依赖。
    """
    if len(password) < MIN_PASSWORD_LEN:
        raise ValueError(f"密码至少 {MIN_PASSWORD_LEN} 位")
    if password.lower() == (username or "").lower():
        raise ValueError("密码不能和用户名相同")
    has_alpha = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    if not (has_alpha and has_digit):
        raise ValueError("密码要同时包含字母和数字")
