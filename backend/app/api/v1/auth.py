"""认证与账户接口（M01 基础；dev-plan P1）。"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.ratelimit import is_locked, record_fail, record_success
from app.core.response import CODE_ALREADY_INITIALIZED, CODE_BAD_CREDENTIALS, BizError, ok
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.session import get_session
from app.models.user import User
from app.schemas.auth import (
    InitRequest,
    LoginRequest,
    PasswordChangeRequest,
    TokenResponse,
    UserInfo,
)

router = APIRouter()


def _issue_tokens(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id, user.token_version),
        refresh_token=create_refresh_token(user.id, user.token_version),
        user=UserInfo.model_validate(user),
    )


@router.post("/auth/init")
async def init_admin(body: InitRequest, session: AsyncSession = Depends(get_session)):
    """首次初始化：仅当系统内无任何用户时可用（M01-2）。"""
    exists = await session.scalar(select(User.id).limit(1))
    if exists is not None:
        raise BizError(CODE_ALREADY_INITIALIZED, "系统已初始化", 403)
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role="admin",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return ok({**_issue_tokens(user).model_dump(), "site_name": body.site_name})


@router.post("/auth/login")
async def login(body: LoginRequest, request: Request, session: AsyncSession = Depends(get_session)):
    """登录（M01-1/6）：失败限速 5 次/分钟（同 IP）。"""
    ip = request.client.host if request.client else "unknown"
    if is_locked(ip):
        raise BizError(1006, "失败次数过多，请 1 分钟后再试", 429)
    user = await session.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        record_fail(ip)
        raise BizError(CODE_BAD_CREDENTIALS, "用户名或密码错误", 401)
    if not user.is_active:
        raise BizError(CODE_BAD_CREDENTIALS, "账号已被禁用", 401)
    record_success(ip)
    return ok(_issue_tokens(user).model_dump())


@router.post("/auth/refresh")
async def refresh(request: Request, session: AsyncSession = Depends(get_session)):
    """用 refresh token 换新 access token（M01-3）。"""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        raise BizError(1002, "缺少 refresh token", 401)
    try:
        payload = decode_token(token, "refresh")
    except Exception:
        raise BizError(1002, "refresh token 无效", 401)
    user = await session.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise BizError(1002, "账号不存在或已禁用", 401)
    if int(payload.get("ver", -1)) != user.token_version:
        raise BizError(1003, "密码已变更，请重新登录", 401)
    new_access = create_access_token(user.id, user.token_version)
    return ok({"access_token": new_access, "token_type": "bearer"})


@router.post("/auth/logout")
async def logout(_: User = Depends(get_current_user)):
    """登出：JWT 无状态，前端清除本地会话即可；接口用于契约完整。"""
    return ok(None, "已登出")


@router.get("/auth/me")
async def me(user: User = Depends(get_current_user)):
    return ok(UserInfo.model_validate(user).model_dump())


@router.put("/auth/password")
async def change_password(
    body: PasswordChangeRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """修改密码（M01-4/5）：校验旧密码与强度；token_version 递增使所有旧会话失效。"""
    if not verify_password(body.old_password, user.password_hash):
        raise BizError(CODE_BAD_CREDENTIALS, "旧密码不正确", 401)
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    user.password_changed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await session.commit()
    return ok(None, "密码已修改，请重新登录")
