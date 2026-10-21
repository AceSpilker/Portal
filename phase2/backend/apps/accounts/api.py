"""认证与账户端点（二期 D2.3–D2.9：自一期 api/v1/auth.py 移植为 Ninja 形态）。

与一期的契约差异（迁移方案 §5.1，有意为之）：
- 登录入参支持 userName（ADP LoginParams）与 username（一期）双写法；
- 登录/init 响应为超集：新增 token/refreshToken（camelCase，ADP 直用），
  旧字段 access_token/refresh_token/token_type/user 全保留；
- 新增 GET /api/user/info（ADP 路由守卫首跳：userId/userName/roles→R_ADMIN·R_USER）。

审计写库 D2.12 接入（当前 _write_audit 静默旁路）。
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone

from django.http import HttpRequest
from ninja import Router, Schema
from pydantic import field_validator

from apps.accounts.deps import get_current_user
from apps.accounts.models import User, UserSession
from apps.accounts.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    refresh_exp,
    refresh_jti,
    verify_password,
)
from apps.accounts.totp import (
    generate_recovery_codes,
    generate_secret,
    hash_recovery_code,
    provisioning_uri,
    verify_code,
    verify_recovery_code,
)
from apps.core.i18n import t
from apps.core.models import Setting
from apps.core.ratelimit import is_locked, record_fail, record_success
from apps.core.response import (
    CODE_ALREADY_INITIALIZED,
    CODE_BAD_CREDENTIALS,
    CODE_NOT_FOUND,
    CODE_TOTP_REQUIRED,
    CODE_VALIDATION,
    BizError,
    ok,
)
from apps.core.stores import stores

router = Router(tags=["auth"])

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")


async def _write_audit(user_id, action: str, detail: str, ip: str) -> None:
    """登录审计落库（D2.12 审计中间件接入前静默旁路）。"""
    return None


# ---- Schemas ----


def _valid_username(v: str) -> str:
    if not _USERNAME_RE.match(v):
        raise ValueError(t("v.username_rule"))
    return v


def _valid_password(v: str) -> str:
    if len(v) < 8 or not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
        raise ValueError(t("v.password_rule"))
    return v


class InitRequest(Schema):
    site_name: str = "Portal"
    username: str
    password: str
    _v_username = field_validator("username")(_valid_username)
    _v_password = field_validator("password")(_valid_password)


class LoginRequest(Schema):
    """userName（ADP）与 username（一期）双写法等价。"""

    username: str | None = None
    userName: str | None = None
    password: str
    totp_code: str | None = None  # 两步验证码 / 恢复码

    @property
    def effective_username(self) -> str:
        return (self.username or self.userName or "").strip()


class PasswordChangeRequest(Schema):
    old_password: str
    new_password: str

    _v_new = field_validator("new_password")(_valid_password)


def _user_view(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "totp_enabled": user.totp_enabled,
    }


def _issue_tokens(user: User) -> dict:
    """超集令牌响应：ADP（token/refreshToken）+ 一期（access_token/...）字段并存。"""
    access = create_access_token(user.id, user.token_version)
    refresh = create_refresh_token(user.id, user.token_version)
    return {
        "token": access,
        "refreshToken": refresh,
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "user": _user_view(user),
    }


async def _setting_bool(key: str) -> bool:
    row = await Setting.objects.filter(key=key).afirst()
    if not row:
        return False
    try:
        return bool(json.loads(row.value))
    except Exception:
        return False


# ---- 初始化 / 公开配置 ----


@router.post("/auth/init")
async def init_admin(request: HttpRequest, body: InitRequest):
    """首次初始化：仅当系统内无任何用户时可用。"""
    if await User.objects.aexists():
        raise BizError(CODE_ALREADY_INITIALIZED, t("err.already_initialized"), 403)
    user = await User.objects.acreate(
        username=body.username,
        password_hash=hash_password(body.password),
        role="admin",
    )
    return ok({**_issue_tokens(user), "site_name": body.site_name})


@router.get("/auth/config")
async def auth_config(request: HttpRequest):
    """公开配置（免认证）：注册开关与登录页企业入口显示。"""
    return ok(
        {
            "allow_register": await _setting_bool("security.allow_register"),
            "oidc_enabled": await _setting_bool("auth.oidc_enabled"),
            "ldap_enabled": await _setting_bool("auth.ldap_enabled"),
        }
    )


@router.post("/auth/register")
async def register(request: HttpRequest, body: InitRequest):
    """开放注册：security.allow_register 开启时可用，默认角色 user。"""
    if not await _setting_bool("security.allow_register"):
        raise BizError(CODE_VALIDATION, t("err.register_disabled"), 403)
    if await User.objects.filter(username=body.username).aexists():
        raise BizError(CODE_VALIDATION, t("err.username_taken"), 422)
    min_row = await Setting.objects.filter(key="security.password_min_length").afirst()
    min_len = int(json.loads(min_row.value)) if min_row else 8
    if len(body.password) < min_len:
        raise BizError(CODE_VALIDATION, t("v.password_short"), 422)
    user = await User.objects.acreate(
        username=body.username, password_hash=hash_password(body.password), role="user"
    )
    return ok({"id": user.id, "username": user.username}, t("ok.registered"))


# ---- 登录 / 令牌 ----


@router.post("/auth/login")
async def login(request: HttpRequest, body: LoginRequest):
    """登录：失败限速 5 次/分钟（同 IP）；TOTP 已启用时需验证码（1007 分支）。"""
    ip = request.META.get("REMOTE_ADDR", "unknown") or "unknown"
    if await is_locked(ip):
        raise BizError(1006, t("err.login_locked"), 429)
    user = await User.objects.filter(username=body.effective_username).afirst()
    if user is None or not verify_password(body.password, user.password_hash):
        await record_fail(ip)
        await _write_audit(user.id if user else None, "login", "bad credentials", ip)
        raise BizError(CODE_BAD_CREDENTIALS, t("err.bad_credentials"), 401)
    if not user.is_active:
        raise BizError(CODE_BAD_CREDENTIALS, t("err.account_disabled"), 401)
    # TOTP 两步验证：验证码或恢复码二选一
    if user.totp_enabled and user.totp_secret:
        code = (body.totp_code or "").strip()
        if not code:
            # 专用码 1007：前端据此展开验证码输入框
            raise BizError(CODE_TOTP_REQUIRED, t("err.totp_code_required"), 422)
        if verify_code(user.totp_secret, code):
            pass
        else:
            hashed = json.loads(user.totp_recovery or "[]")
            if not verify_recovery_code(code, hashed):
                raise BizError(CODE_VALIDATION, t("err.totp_code_invalid"), 422)
            # 恢复码命中即销毁（单次有效）
            user.totp_recovery = json.dumps(
                [h for h in hashed if h != hash_recovery_code(code)]
            )
            await user.asave()
    await record_success(ip)
    await _write_audit(user.id, "login", f"ok ip={ip}", ip)
    result = _issue_tokens(user)
    # 会话登记：refresh jti 定位会话（设备管理/强制下线）
    jti = refresh_jti(result["refresh_token"])
    if jti:
        from django.utils import timezone as dj_tz

        ua = (request.headers.get("User-Agent", "") or "")[:200]
        exp_naive = refresh_exp(result["refresh_token"])
        await UserSession.objects.acreate(
            user_id=user.id,
            jti=jti,
            device=ua,
            ip=ip,
            expires_at=dj_tz.make_aware(exp_naive) if exp_naive else None,
        )
    return ok(result)


@router.post("/auth/refresh")
async def refresh(request: HttpRequest):
    """用 refresh token 换新 access token（Authorization 头携带）。"""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        raise BizError(1002, t("err.token_missing"), 401)
    try:
        payload = decode_token(token, "refresh")
    except Exception:
        raise BizError(1002, t("err.refresh_invalid"), 401)
    user = await User.objects.filter(pk=int(payload["sub"])).afirst()
    if user is None or not user.is_active:
        raise BizError(1002, t("err.account_invalid"), 401)
    if int(payload.get("ver", -1)) != user.token_version:
        raise BizError(1003, t("err.password_changed"), 401)
    # 会话吊销校验：被吊销/被踢设备的 refresh 一律拒绝
    jti = payload.get("jti")
    if jti:
        revoked = await UserSession.objects.filter(jti=jti).values_list(
            "revoked", flat=True
        ).afirst()
        if revoked:  # True=revoked；None=旧会话无记录（升级前签发），放行
            raise BizError(1002, t("err.session_revoked_login"), 401)
    return ok({"access_token": create_access_token(user.id, user.token_version),
               "token_type": "bearer"})


@router.post("/auth/logout")
async def logout(request: HttpRequest):
    """登出（需登录）：访问令牌 jti 入黑名单（TTL=剩余有效期）。"""
    await get_current_user(request)  # 确保登录态（ninja 1.7 无 Depends 注入，端点内自校验）
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if token and not token.startswith("plt_"):
        try:
            payload = decode_token(token, "access")
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti and exp:
                ttl = int(float(exp) - time.time())
                if ttl > 0:
                    await stores.store.set(f"bl:{jti}", "1", ttl=ttl)
        except Exception:
            pass  # 令牌本已无效/无 jti，登出保持成功
    return ok(None, t("ok.logged_out"))


# ---- 用户信息 ----


@router.get("/auth/me")
async def me(request: HttpRequest):
    user = await get_current_user(request)
    return ok(_user_view(user))


@router.get("/user/info")
async def user_info(request: HttpRequest):
    """ADP 契约端点：路由守卫首跳拉取，roles 驱动菜单过滤。"""
    user = await get_current_user(request)
    return ok(
        {
            "userId": user.id,
            "userName": user.username,
            "email": "",
            "avatar": "",
            "roles": ["R_ADMIN"] if user.role == "admin" else ["R_USER"],
            "buttons": [],
        }
    )


@router.put("/auth/password")
async def change_password(request: HttpRequest, body: PasswordChangeRequest):
    """修改密码：校验旧密码与强度；token_version 递增使所有旧会话失效。"""
    user = await get_current_user(request)
    if not verify_password(body.old_password, user.password_hash):
        raise BizError(CODE_BAD_CREDENTIALS, t("err.old_password"), 401)
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    user.password_changed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await user.asave()
    return ok(None, t("ok.password_changed"))


# ---- TOTP 两步验证 ----


@router.post("/auth/totp/setup")
async def totp_setup(request: HttpRequest):
    """生成 TOTP 密钥（未启用态）：返回 otpauth URI，前端转二维码。"""
    user = await get_current_user(request)
    if user.totp_enabled:
        raise BizError(CODE_VALIDATION, t("err.totp_already"), 422)
    user.totp_secret = generate_secret()
    user.totp_recovery = json.dumps([])
    await user.asave()
    return ok(
        {
            "secret": user.totp_secret,
            "otpauth_uri": provisioning_uri(user.totp_secret, user.username),
        }
    )


class TotpEnableRequest(Schema):
    code: str = ""


class TotpDisableRequest(Schema):
    password: str = ""
    code: str = ""


@router.post("/auth/totp/enable")
async def totp_enable(request: HttpRequest, body: TotpEnableRequest):
    """校验验证码并启用；返回恢复码（仅此一次明文展示）。"""
    user = await get_current_user(request)
    if user.totp_enabled or not user.totp_secret:
        raise BizError(CODE_VALIDATION, t("err.totp_not_setup"), 422)
    code = body.code.strip()
    if not verify_code(user.totp_secret, code):
        raise BizError(CODE_VALIDATION, t("err.totp_code_invalid"), 422)
    user.totp_enabled = True
    codes = generate_recovery_codes()
    user.totp_recovery = json.dumps([hash_recovery_code(c) for c in codes])
    await user.asave()
    return ok({"recovery_codes": codes}, t("ok.totp_enabled"))


@router.post("/auth/totp/disable")
async def totp_disable(request: HttpRequest, body: TotpDisableRequest):
    """关闭两步验证：需密码 + 当前验证码。"""
    user = await get_current_user(request)
    if not user.totp_enabled:
        raise BizError(CODE_VALIDATION, t("err.totp_not_enabled"), 422)
    if not verify_password(body.password, user.password_hash):
        raise BizError(CODE_BAD_CREDENTIALS, t("err.old_password"), 401)
    if not verify_code(user.totp_secret or "", body.code.strip()):
        raise BizError(CODE_VALIDATION, t("err.totp_code_invalid"), 422)
    user.totp_enabled = False
    user.totp_secret = None
    user.totp_recovery = "[]"
    await user.asave()
    return ok(None, t("ok.totp_disabled"))


# ---- 会话/设备管理 ----


def _iso_utc(dt) -> str | None:
    return dt.isoformat() + "+00:00" if dt else None


def _session_view(row: UserSession) -> dict:
    return {
        "id": row.id,
        "device": row.device,
        "ip": row.ip,
        "created_at": _iso_utc(row.created_at),
        "last_seen_at": _iso_utc(row.last_seen_at),
        "revoked": row.revoked,
    }


@router.get("/auth/sessions")
async def list_sessions(request: HttpRequest):
    """当前用户会话清单（设备/UA/IP/最近活跃）。"""
    user = await get_current_user(request)
    rows = [
        row
        async for row in UserSession.objects.filter(user_id=user.id, revoked=False).order_by(
            "-last_seen_at", "-created_at"
        )
    ]
    return ok([_session_view(r) for r in rows])


@router.delete("/auth/sessions/{session_id}")
async def revoke_session(request: HttpRequest, session_id: int):
    """吊销会话（下线该设备；refresh 立即失效）。"""
    user = await get_current_user(request)
    row = await UserSession.objects.filter(pk=session_id, user_id=user.id).afirst()
    if row is None:
        raise BizError(CODE_NOT_FOUND, t("err.session_not_found"), 404)
    row.revoked = True
    await row.asave()
    return ok({"id": session_id}, t("ok.session_revoked"))
