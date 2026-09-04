"""认证与账户接口（M01 基础；dev-plan P1）。"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.i18n import t
from app.core.ratelimit import is_locked, record_fail, record_success
from app.core.response import (
    CODE_ALREADY_INITIALIZED,
    CODE_BAD_CREDENTIALS,
    CODE_NOT_FOUND,
    CODE_TOTP_REQUIRED,
    CODE_VALIDATION,
    BizError,
    ok,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    refresh_exp,
    refresh_jti,
    verify_password,
)
from app.db.session import get_session
from app.models.api_token import UserSession
from app.models.setting import Setting
from app.models.user import User
from app.schemas.auth import (
    InitRequest,
    LoginRequest,
    PasswordChangeRequest,
    TokenResponse,
    UserInfo,
)
from app.services import totp as totp_svc

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
        raise BizError(CODE_ALREADY_INITIALIZED, t("err.already_initialized"), 403)
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role="admin",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return ok({**_issue_tokens(user).model_dump(), "site_name": body.site_name})


async def _setting_bool(session: AsyncSession, key: str) -> bool:
    import json

    row = await session.get(Setting, key)
    return bool(json.loads(row.value)) if row else False


@router.get("/auth/config")
async def auth_config(session: AsyncSession = Depends(get_session)):
    """公开配置（免认证）：注册开关（登录页显示注册入口用）。"""
    return ok({"allow_register": await _setting_bool(session, "security.allow_register")})


@router.post("/auth/register")
async def register(body: InitRequest, session: AsyncSession = Depends(get_session)):
    """开放注册（M15-2；P17.3）：security.allow_register 开启时可用，默认角色 user。"""
    if not await _setting_bool(session, "security.allow_register"):
        raise BizError(CODE_VALIDATION, t("err.register_disabled"), 403)
    exists = await session.scalar(select(User.id).where(User.username == body.username))
    if exists is not None:
        raise BizError(CODE_VALIDATION, t("err.username_taken"), 422)
    import json as _json

    min_row = await session.get(Setting, "security.password_min_length")
    min_len = int(_json.loads(min_row.value)) if min_row else 8
    if len(body.password) < min_len:
        raise BizError(CODE_VALIDATION, t("v.password_short"), 422)
    user = User(username=body.username, password_hash=hash_password(body.password), role="user")
    session.add(user)
    await session.commit()
    return ok({"id": user.id, "username": user.username}, t("ok.registered"))


@router.post("/auth/login")
async def login(body: LoginRequest, request: Request, session: AsyncSession = Depends(get_session)):
    """登录（M01-1/6）：失败限速 5 次/分钟（同 IP）；TOTP 已启用时需验证码。"""
    ip = request.client.host if request.client else "unknown"
    if is_locked(ip):
        raise BizError(1006, t("err.login_locked"), 429)
    user = await session.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        record_fail(ip)
        from app.services.audit import client_ip, write_audit

        await write_audit(
            session, user.id if user else None, "login", "bad credentials", client_ip(request)
        )
        raise BizError(CODE_BAD_CREDENTIALS, t("err.bad_credentials"), 401)
    if not user.is_active:
        raise BizError(CODE_BAD_CREDENTIALS, t("err.account_disabled"), 401)
    # TOTP 两步验证（P17.1/M01-7）：验证码或恢复码二选一
    if user.totp_enabled and user.totp_secret:
        code = (body.totp_code or "").strip()
        if not code:
            # 专用码 1007：前端据此展开验证码输入框
            raise BizError(CODE_TOTP_REQUIRED, t("err.totp_code_required"), 422)
        if totp_svc.verify_code(user.totp_secret, code):
            pass
        else:
            import json

            hashed = json.loads(user.totp_recovery or "[]")
            if not totp_svc.verify_recovery_code(code, hashed):
                raise BizError(CODE_VALIDATION, t("err.totp_code_invalid"), 422)
            # 恢复码命中即销毁（单次有效）
            rest = [h for h in hashed if h != totp_svc.hash_recovery_code(code)]
            user.totp_recovery = json.dumps(rest)
    record_success(ip)
    from app.services.audit import client_ip, write_audit

    await write_audit(session, user.id, "login", f"ok ip={ip}", client_ip(request))
    result = _issue_tokens(user).model_dump()
    # 会话登记（P17.1/M01-8）：refresh jti 定位会话
    jti = refresh_jti(result["refresh_token"])
    if jti:
        ua = (request.headers.get("user-agent", "") or "")[:200]
        session.add(
            UserSession(
                user_id=user.id,
                jti=jti,
                device=ua,
                ip=ip,
                expires_at=refresh_exp(result["refresh_token"]),
            )
        )
        await session.commit()
    return ok(result)


@router.post("/auth/refresh")
async def refresh(request: Request, session: AsyncSession = Depends(get_session)):
    """用 refresh token 换新 access token（M01-3）。"""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        raise BizError(1002, t("err.token_missing"), 401)
    try:
        payload = decode_token(token, "refresh")
    except Exception:
        raise BizError(1002, t("err.refresh_invalid"), 401)
    user = await session.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise BizError(1002, t("err.account_invalid"), 401)
    if int(payload.get("ver", -1)) != user.token_version:
        raise BizError(1003, t("err.password_changed"), 401)
    # 会话吊销校验（P17.1/M01-8）：被吊销/被踢设备的 refresh 一律拒绝
    from sqlalchemy import select as _select

    from app.models.api_token import UserSession as _US

    jti = payload.get("jti")
    if jti:
        row = (
            await session.execute(_select(_US.revoked).where(_US.jti == jti))
        ).scalar_one_or_none()
        if row:  # True=revoked；None=旧会话无记录（升级前签发），放行
            raise BizError(1002, t("err.session_revoked_login"), 401)
    new_access = create_access_token(user.id, user.token_version)
    return ok({"access_token": new_access, "token_type": "bearer"})


@router.post("/auth/logout")
async def logout(_: User = Depends(get_current_user)):
    """登出：JWT 无状态，前端清除本地会话即可；接口用于契约完整。"""
    return ok(None, t("ok.logged_out"))


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
        raise BizError(CODE_BAD_CREDENTIALS, t("err.old_password"), 401)
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    user.password_changed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await session.commit()
    return ok(None, t("ok.password_changed"))


# ---- TOTP 两步验证（M01-7；P17.1）----


@router.post("/auth/totp/setup")
async def totp_setup(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    """生成 TOTP 密钥（未启用态）：返回 otpauth URI，前端转二维码。"""
    if user.totp_enabled:
        raise BizError(CODE_VALIDATION, t("err.totp_already"), 422)
    import json as _json

    user.totp_secret = totp_svc.generate_secret()
    user.totp_recovery = _json.dumps([])
    await session.commit()
    return ok(
        {
            "secret": user.totp_secret,
            "otpauth_uri": totp_svc.provisioning_uri(user.totp_secret, user.username),
        }
    )


@router.post("/auth/totp/enable")
async def totp_enable(
    body: dict,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """校验验证码并启用；返回恢复码（仅此一次明文展示）。"""
    import json as _json

    if user.totp_enabled or not user.totp_secret:
        raise BizError(CODE_VALIDATION, t("err.totp_not_setup"), 422)
    code = str(body.get("code", "")).strip()
    if not totp_svc.verify_code(user.totp_secret, code):
        raise BizError(CODE_VALIDATION, t("err.totp_code_invalid"), 422)
    user.totp_enabled = True
    codes = totp_svc.generate_recovery_codes()
    user.totp_recovery = _json.dumps([totp_svc.hash_recovery_code(c) for c in codes])
    await session.commit()
    return ok({"recovery_codes": codes}, t("ok.totp_enabled"))


@router.post("/auth/totp/disable")
async def totp_disable(
    body: dict,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """关闭两步验证：需密码 + 当前验证码。"""
    if not user.totp_enabled:
        raise BizError(CODE_VALIDATION, t("err.totp_not_enabled"), 422)
    if not verify_password(str(body.get("password", "")), user.password_hash):
        raise BizError(CODE_BAD_CREDENTIALS, t("err.old_password"), 401)
    if not totp_svc.verify_code(user.totp_secret or "", str(body.get("code", "")).strip()):
        raise BizError(CODE_VALIDATION, t("err.totp_code_invalid"), 422)
    user.totp_enabled = False
    user.totp_secret = None
    user.totp_recovery = "[]"
    await session.commit()
    return ok(None, t("ok.totp_disabled"))


# ---- 会话/设备管理（M01-8；P17.1）----


def _session_view(row: UserSession) -> dict:
    return {
        "id": row.id,
        "device": row.device,
        "ip": row.ip,
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        "last_seen_at": row.last_seen_at.isoformat() + "Z" if row.last_seen_at else None,
        "revoked": row.revoked,
    }


@router.get("/auth/sessions")
async def list_sessions(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    """当前用户会话清单（设备/UA/IP/最近活跃）。"""
    rows = (
        (
            await session.execute(
                select(UserSession)
                .where(UserSession.user_id == user.id, UserSession.revoked.is_(False))
                .order_by(UserSession.last_seen_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return ok([_session_view(r) for r in rows])


@router.delete("/auth/sessions/{session_id}")
async def revoke_session(
    session_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """吊销会话（下线该设备；refresh 立即失效）。"""
    row = await session.get(UserSession, session_id)
    if row is None or row.user_id != user.id:
        raise BizError(CODE_NOT_FOUND, t("err.session_not_found"), 404)
    row.revoked = True
    await session.commit()
    return ok({"id": session_id}, t("ok.session_revoked"))
