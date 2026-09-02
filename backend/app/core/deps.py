"""FastAPI 依赖：当前用户 / 管理员权限（M01-9）。"""

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import t
from app.core.response import CODE_TOKEN_EXPIRED, CODE_TOKEN_INVALID, BizError
from app.core.security import decode_token
from app.db.session import get_session
from app.models.user import User

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    if cred is None:
        raise BizError(CODE_TOKEN_INVALID, t("err.unauthenticated"), 401)
    try:
        payload = decode_token(cred.credentials, "access")
    except jwt.ExpiredSignatureError:
        raise BizError(CODE_TOKEN_EXPIRED, t("err.token_expired"), 401)
    except jwt.PyJWTError:
        raise BizError(CODE_TOKEN_INVALID, t("err.token_invalid"), 401)

    user = await session.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise BizError(CODE_TOKEN_INVALID, t("err.account_invalid"), 401)
    # 改密会使 token_version 递增：旧版本 token 一律失效（M01-4 改密踢会话）
    if int(payload.get("ver", -1)) != user.token_version:
        raise BizError(CODE_TOKEN_EXPIRED, t("err.password_changed"), 401)
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise BizError(3001, t("err.admin_required"), 403)
    return user
