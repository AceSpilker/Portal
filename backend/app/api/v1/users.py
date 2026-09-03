"""用户管理接口（M01-11；dev-plan 7.4；api-spec §4.2）。

权限：全部仅管理员（M）。边界规则：
- 不物理删除用户（audit_logs 引用），仅禁用；
- 不能对自己执行禁用/降级/踢出/重置密码；
- 全库至少保留 1 个启用中的 admin（违反 4003）；
- username 唯一（4002）；
- 全部管理操作写 audit_logs。
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.core.i18n import t
from app.core.response import CODE_DUPLICATED, CODE_FORBIDDEN, BizError, ok
from app.core.security import hash_password
from app.db.session import get_session
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.auth import validate_password, validate_username

router = APIRouter()


# ---- Pydantic 模型 ----


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = Field(default="user", pattern="^(admin|user)$")
    remark: str = Field(default="", max_length=256)

    _v_username = field_validator("username")(validate_username)
    _v_password = field_validator("password")(validate_password)


class UserUpdate(BaseModel):
    role: str = Field(pattern="^(admin|user)$")
    remark: str = Field(default="", max_length=256)


class UserStatusUpdate(BaseModel):
    enabled: bool


class UserPasswordReset(BaseModel):
    password: str

    _v_password = field_validator("password")(validate_password)


# ---- 审计 ----


async def write_audit(
    session: AsyncSession,
    user_id: int | None,
    action: str,
    detail: str,
    request_ip: str = "",
) -> None:
    session.add(AuditLog(user_id=user_id, action=action, detail=detail, ip=request_ip))


def _client_ip(request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    return xff.split(",")[0].strip() if xff else (request.client.host if request.client else "")


# ---- 边界检查 ----


async def _count_enabled_admins(session: AsyncSession, exclude_id: int | None = None) -> int:
    stmt = select(func.count(User.id)).where(
        User.role == "admin", User.is_active.is_(True)
    )
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return (await session.execute(stmt)).scalar_one()


def _guard_not_self(operator: User, target_id: int, action: str) -> None:
    if operator.id == target_id:
        raise BizError(CODE_FORBIDDEN, t("err.user_self_action", action=action), 403)


async def _guard_keep_admin(session: AsyncSession, target: User, action: str) -> None:
    if target.role == "admin" and target.is_active:
        remaining = await _count_enabled_admins(session, exclude_id=target.id)
        if remaining == 0:
            raise BizError(CODE_FORBIDDEN, t("err.last_admin", action=action), 403)


# ---- 接口 ----


def _user_view(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "is_active": bool(u.is_active),
        "remark": u.remark or "",
        "token_version": u.token_version,
        "created_at": u.created_at.isoformat() + "Z" if u.created_at else None,
    }


@router.get("/users")
async def list_users(
    keyword: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """用户列表（分页 + 用户名/备注搜索；不回传密码哈希）。"""
    stmt = select(User)
    kw = keyword.strip()
    if kw:
        like = f"%{kw}%"
        stmt = stmt.where(or_(User.username.ilike(like), User.remark.ilike(like)))
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(User.id).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars()
    return ok(
        {
            "items": [_user_view(u) for u in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("/users")
async def create_user(
    body: UserCreate,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    dup = (
        await session.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    if dup:
        raise BizError(CODE_DUPLICATED, t("err.username_dup"), 409)
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role=body.role,
        remark=body.remark,
    )
    session.add(user)
    await session.commit()
    await write_audit(
        session, admin.id, "user_create",
        f"创建用户 {body.username}（{body.role}）", _client_ip(request),
    )
    await session.commit()
    return ok(_user_view(user))


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    body: UserUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(User, user_id)
    if user is None:
        raise BizError(CODE_FORBIDDEN, t("err.user_not_found"), 404)
    if user.id == admin.id and body.role != "admin":
        raise BizError(CODE_FORBIDDEN, t("err.user_self_action", action="修改自己的角色"), 403)
    if user.role == "admin" and body.role != "admin":
        await _guard_keep_admin(session, user, "降级")
    user.role = body.role
    user.remark = body.remark
    await session.commit()
    await write_audit(
        session, admin.id, "user_update",
        f"编辑用户 {user.username}（{body.role}）", _client_ip(request),
    )
    await session.commit()
    return ok(_user_view(user))


@router.put("/users/{user_id}/status")
async def set_user_status(
    user_id: int,
    body: UserStatusUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    _guard_not_self(admin, user_id, "禁用自己")
    user = await session.get(User, user_id)
    if user is None:
        raise BizError(CODE_FORBIDDEN, t("err.user_not_found"), 404)
    if body.enabled:
        user.is_active = True
    else:
        await _guard_keep_admin(session, user, "禁用")
        user.is_active = False
        user.token_version += 1  # 禁用即全部会话失效
    await session.commit()
    await write_audit(
        session, admin.id, "user_status",
        f"{'启用' if body.enabled else '禁用'}用户 {user.username}", _client_ip(request),
    )
    await session.commit()
    return ok(_user_view(user))


@router.put("/users/{user_id}/password")
async def reset_user_password(
    user_id: int,
    body: UserPasswordReset,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(User, user_id)
    if user is None:
        raise BizError(CODE_FORBIDDEN, t("err.user_not_found"), 404)
    user.password_hash = hash_password(body.password)
    user.token_version += 1  # 全部会话失效
    user.password_changed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await session.commit()
    await write_audit(
        session, admin.id, "user_reset_password",
        f"重置用户 {user.username} 的密码", _client_ip(request),
    )
    await session.commit()
    return ok(None, t("ok.user_password_reset"))


@router.post("/users/{user_id}/kick")
async def kick_user(
    user_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    _guard_not_self(admin, user_id, "踢出自己")
    user = await session.get(User, user_id)
    if user is None:
        raise BizError(CODE_FORBIDDEN, t("err.user_not_found"), 404)
    user.token_version += 1
    await session.commit()
    await write_audit(
        session, admin.id, "user_kick",
        f"强制下线用户 {user.username}", _client_ip(request),
    )
    await session.commit()
    return ok(None, t("ok.user_kicked"))
