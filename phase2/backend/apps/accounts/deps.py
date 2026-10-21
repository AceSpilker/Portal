"""认证依赖（二期 D2.1：自一期 core/deps.py 移植为 Ninja Depends 形态）。

双通道鉴权：Authorization 头（Bearer 可选前缀——ADP 拦截器原样发 token）承载
JWT access 或 plt_ API Token；ro Token 写操作 403；登出黑名单 jti 拦截；
token_version 不匹配（改密踢会话）一律 1003。
"""

from __future__ import annotations

import hashlib

import jwt as pyjwt
from django.http import HttpRequest

from apps.accounts.models import ApiToken, User
from apps.accounts.security import decode_token
from apps.core.i18n import t
from apps.core.response import CODE_TOKEN_EXPIRED, CODE_TOKEN_INVALID, BizError
from apps.core.stores import stores

TOKEN_PREFIX = "plt_"
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


class AuthContext:
    """认证结果：用户 + 来源（jwt/api_token）；ro Token 写操作在此拦截。"""

    def __init__(self, user: User, source: str, scope: str = "rw") -> None:
        self.user = user
        self.source = source
        self.scope = scope


def _bearer_token(request: HttpRequest) -> str:
    authz = request.headers.get("Authorization", "")
    # Bearer 前缀可选：兼容 "Bearer <jwt>" 与 ADP 拦截器的裸 token 两种形态
    if authz.startswith("Bearer "):
        return authz[len("Bearer ") :].strip()
    return authz.strip()


async def _user_from_api_token(raw: str, request: HttpRequest) -> AuthContext:
    from datetime import datetime
    from datetime import timezone as _tz

    digest = hashlib.sha256(raw.encode()).hexdigest()
    row = await ApiToken.objects.filter(token_hash=digest, revoked=False).afirst()
    if row is None:
        raise BizError(CODE_TOKEN_INVALID, t("err.token_invalid"), 401)
    if row.expires_at is not None and row.expires_at <= datetime.now(_tz.utc):
        raise BizError(CODE_TOKEN_EXPIRED, t("err.token_expired"), 401)
    user = await User.objects.aget(pk=row.user_id) if await User.objects.filter(
        pk=row.user_id
    ).aexists() else None
    if user is None or not user.is_active:
        raise BizError(CODE_TOKEN_INVALID, t("err.account_invalid"), 401)
    await ApiToken.objects.filter(pk=row.pk).aupdate(last_used_at=datetime.now(_tz.utc))
    # ro 范围：非安全方法直接 403（只读/读写两档）
    if row.scope == "ro" and request.method not in SAFE_METHODS:
        raise BizError(3001, t("err.token_readonly"), 403)
    return AuthContext(user=user, source="api_token", scope=row.scope)


async def get_auth_context(request: HttpRequest) -> AuthContext:
    raw = _bearer_token(request)
    if not raw:
        raise BizError(CODE_TOKEN_INVALID, t("err.token_invalid"), 401)
    if raw.startswith(TOKEN_PREFIX):
        return await _user_from_api_token(raw, request)
    try:
        payload = decode_token(raw, "access")
    except pyjwt.ExpiredSignatureError:
        raise BizError(CODE_TOKEN_EXPIRED, t("err.token_expired"), 401)
    except pyjwt.PyJWTError:
        raise BizError(CODE_TOKEN_INVALID, t("err.token_invalid"), 401)

    # 登出黑名单：jti 命中即拒绝
    jti = payload.get("jti")
    if jti and await stores.store.exists(f"bl:{jti}"):
        raise BizError(CODE_TOKEN_EXPIRED, t("err.token_expired"), 401)

    user = await User.objects.filter(pk=int(payload["sub"])).afirst()
    if user is None or not user.is_active:
        raise BizError(CODE_TOKEN_INVALID, t("err.account_invalid"), 401)
    # 改密使 token_version 递增：旧版本 token 一律失效
    if int(payload.get("ver", -1)) != user.token_version:
        raise BizError(CODE_TOKEN_EXPIRED, t("err.password_changed"), 401)
    return AuthContext(user=user, source="jwt")


async def get_current_user(request: HttpRequest) -> User:
    return (await get_auth_context(request)).user


async def require_admin(request: HttpRequest) -> User:
    user = await get_current_user(request)
    if user.role != "admin":
        raise BizError(3001, t("err.admin_required"), 403)
    return user
