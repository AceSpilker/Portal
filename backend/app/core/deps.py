"""FastAPI 依赖：当前用户 / 管理员权限（M01-9）+ API Token 鉴权（M14-1，P17.2）。"""

import hashlib
from datetime import datetime

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import t
from app.core.response import CODE_TOKEN_EXPIRED, CODE_TOKEN_INVALID, BizError
from app.core.security import decode_token
from app.db.session import get_session
from app.models.user import User

_bearer = HTTPBearer(auto_error=False)

TOKEN_PREFIX = "plt_"
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


class AuthContext:
    """认证结果：用户 + 来源（jwt/api_token）；ro Token 写操作在 require_write 拦截。"""

    def __init__(self, user: User, source: str, scope: str = "rw") -> None:
        self.user = user
        self.source = source
        self.scope = scope


async def _user_from_api_token(raw: str, session: AsyncSession, request: Request) -> AuthContext:
    from app.models.api_token import ApiToken as _T

    digest = hashlib.sha256(raw.encode()).hexdigest()
    row = (
        await session.execute(select(_T).where(_T.token_hash == digest, _T.revoked.is_(False)))
    ).scalar_one_or_none()
    if row is None:
        raise BizError(CODE_TOKEN_INVALID, t("err.token_invalid"), 401)
    if row.expires_at is not None and row.expires_at <= datetime.utcnow():
        raise BizError(CODE_TOKEN_EXPIRED, t("err.token_expired"), 401)
    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise BizError(CODE_TOKEN_INVALID, t("err.account_invalid"), 401)
    row.last_used_at = datetime.utcnow()
    await session.commit()
    # ro 范围：非安全方法直接 403（M14-1 只读/读写）
    if row.scope == "ro" and request.method not in SAFE_METHODS:
        raise BizError(3001, t("err.token_readonly"), 403)
    return AuthContext(user=user, source="api_token", scope=row.scope)


async def get_current_user(
    request: Request,
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    ctx = await get_auth_context(request, cred, session)
    return ctx.user


async def get_auth_context(
    request: Request,
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> AuthContext:
    """JWT 与 API Token 双通道鉴权（P17.2：Bearer plt_… 走 Token 表）。"""
    if cred is None:
        raise BizError(CODE_TOKEN_INVALID, t("err.unauthenticated"), 401)
    raw = cred.credentials
    if raw.startswith(TOKEN_PREFIX):
        return await _user_from_api_token(raw, session, request)
    try:
        payload = decode_token(raw, "access")
    except jwt.ExpiredSignatureError:
        raise BizError(CODE_TOKEN_EXPIRED, t("err.token_expired"), 401)
    except jwt.PyJWTError:
        raise BizError(CODE_TOKEN_INVALID, t("err.token_invalid"), 401)

    # 登出黑名单（P25.2）：jti 命中即拒绝
    jti = payload.get("jti")
    if jti:
        from app.core.stores import stores

        if await stores.store.exists(f"bl:{jti}"):
            raise BizError(CODE_TOKEN_EXPIRED, t("err.token_expired"), 401)

    user = await session.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise BizError(CODE_TOKEN_INVALID, t("err.account_invalid"), 401)
    # 改密会使 token_version 递增：旧版本 token 一律失效（M01-4 改密踢会话）
    if int(payload.get("ver", -1)) != user.token_version:
        raise BizError(CODE_TOKEN_EXPIRED, t("err.password_changed"), 401)
    return AuthContext(user=user, source="jwt")


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise BizError(3001, t("err.admin_required"), 403)
    return user
