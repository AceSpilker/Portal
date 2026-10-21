"""密码哈希（bcrypt）与 JWT 签发/校验（二期 D2.1：自一期 core/security.py 逐行移植）。"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from django.conf import settings

ALGORITHM = "HS256"
ACCESS_EXPIRE_MIN = 30
REFRESH_EXPIRE_DAYS = 7


# ---- 密码 ----


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


# ---- JWT ----


def _create_token(
    user_id: int, token_type: str, expires_delta: timedelta, ver: int
) -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    iat = int(now.timestamp())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": token_type,
        "iat": iat,
        "exp": now + expires_delta,
        "ver": ver,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM), iat


def create_signed_token(payload: dict[str, Any], token_type: str, expires_delta: timedelta) -> str:
    """通用短时签名令牌（文件预览/隧道/OIDC state）；sub/ver 语义由调用方定义。"""
    now = datetime.now(timezone.utc)
    body = {
        **payload,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": now + expires_delta,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(body, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(user_id: int, token_version: int = 0) -> str:
    token, _ = _create_token(user_id, "access", timedelta(minutes=ACCESS_EXPIRE_MIN), token_version)
    return token


def create_refresh_token(user_id: int, token_version: int = 0) -> str:
    token, _ = _create_token(user_id, "refresh", timedelta(days=REFRESH_EXPIRE_DAYS), token_version)
    return token


def refresh_jti(token: str) -> str | None:
    """解出 refresh token 的 jti（会话清单定位用）；失败返回 None。"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("jti")
    except Exception:
        return None


def refresh_exp(token: str) -> datetime | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        exp = payload.get("exp")
        if not exp:
            return None
        return datetime.fromtimestamp(float(exp), tz=timezone.utc).replace(tzinfo=None)
    except Exception:
        return None


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    """校验并解码；失败抛 jwt.PyJWTError，调用方转业务错误。"""
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("token type mismatch")
    return payload
