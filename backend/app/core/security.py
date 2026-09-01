"""密码哈希（bcrypt）与 JWT 签发/校验（dev-plan P1.2）。"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

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
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM), iat


def create_access_token(user_id: int, token_version: int = 0) -> str:
    token, _ = _create_token(user_id, "access", timedelta(minutes=ACCESS_EXPIRE_MIN), token_version)
    return token


def create_refresh_token(user_id: int, token_version: int = 0) -> str:
    token, _ = _create_token(user_id, "refresh", timedelta(days=REFRESH_EXPIRE_DAYS), token_version)
    return token


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    """校验并解码；失败抛 jwt.PyJWTError，调用方转业务错误。"""
    payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("token type mismatch")
    return payload
