"""企业登录接口（M01-12/13；dev-plan P22.1；api-spec §4.1）。

- GET/PUT /api/auth/enterprise：OIDC / LDAP 配置（client_secret Fernet 加密、脱敏）；
- GET /api/auth/oidc/authorize：生成授权跳转 URL（state 签名防 CSRF）；
- POST /api/auth/oidc/callback：授权码换令牌 → userinfo → 查找/自动开通用户 → 签发会话；
- POST /api/auth/ldap/login：LDAP 绑定认证 → 查找/自动开通用户 → 签发会话。
Passkey/WebAuthn 为远期预留（见 dev-plan P22 说明）。
"""

from __future__ import annotations

from datetime import timedelta

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.core.i18n import t
from app.core.response import CODE_BAD_CREDENTIALS, CODE_VALIDATION, BizError, ok
from app.core.secret_box import decrypt_secret, encrypt_secret
from app.core.security import create_access_token, create_refresh_token, hash_password
from app.db.session import get_session
from app.models.setting import Setting
from app.models.user import User

router = APIRouter()

ENTERPRISE_KEYS = (
    "auth.oidc_enabled", "auth.oidc_issuer", "auth.oidc_client_id",
    "auth.oidc_client_secret", "auth.ldap_enabled", "auth.ldap_server",
    "auth.ldap_base_dn", "auth.ldap_bind_dn_tpl",
)


async def get_config(session: AsyncSession) -> dict:
    cfg: dict = {}
    for key in ENTERPRISE_KEYS:
        row = await session.get(Setting, key)
        cfg[key.split(".", 1)[1]] = _json_loads(row.value) if row else None
    cfg["oidc_client_secret"] = decrypt_secret(str(cfg.get("oidc_client_secret") or ""))
    cfg["oidc_enabled"] = bool(cfg.get("oidc_enabled"))
    cfg["ldap_enabled"] = bool(cfg.get("ldap_enabled"))
    return cfg


def _json_loads(raw: str):
    import json as _json

    return _json.loads(raw)


def _json_dumps(value) -> str:
    import json as _json

    return _json.dumps(value)


def _mask(cfg: dict) -> dict:
    out = dict(cfg)
    out["client_secret_set"] = bool(cfg.get("oidc_client_secret"))
    out["oidc_client_secret"] = ""
    return out


async def save_config(session: AsyncSession, body: dict) -> None:
    mapping = {
        "oidc_enabled": bool(body.get("oidc_enabled", False)),
        "oidc_issuer": str(body.get("oidc_issuer", ""))[:253],
        "oidc_client_id": str(body.get("oidc_client_id", ""))[:128],
        "ldap_enabled": bool(body.get("ldap_enabled", False)),
        "ldap_server": str(body.get("ldap_server", ""))[:253],
        "ldap_base_dn": str(body.get("ldap_base_dn", ""))[:253],
        "ldap_bind_dn_tpl": str(
            body.get("ldap_bind_dn_tpl", "uid={username},ou=people,{base_dn}")
        )[:253],
    }
    for suffix, value in mapping.items():
        await session.merge(Setting(key=f"auth.{suffix}", value=_json_dumps(value)))
    secret = str(body.get("oidc_client_secret", ""))
    if secret:  # 空=保持原值
        await session.merge(
            Setting(key="auth.oidc_client_secret", value=_json_dumps(encrypt_secret(secret)))
        )


@router.get("/auth/enterprise")
async def enterprise_config(
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    return ok(_mask(await get_config(session)))


class EnterpriseBody(BaseModel):
    oidc_enabled: bool = False
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    ldap_enabled: bool = False
    ldap_server: str = ""
    ldap_base_dn: str = ""
    ldap_bind_dn_tpl: str = "uid={username},ou=people,{base_dn}"


@router.put("/auth/enterprise")
async def update_enterprise(
    body: EnterpriseBody,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    await save_config(session, body.model_dump())
    await session.commit()
    return ok(_mask(await get_config(session)), t("ok.saved"))


# ---- OIDC 授权码（M01-12；P22.1）----

AUTH_LIFETIME = 600  # code/state 有效期（秒）


@router.get("/auth/oidc/authorize")
async def oidc_authorize(session: AsyncSession = Depends(get_session)):
    """生成 OIDC 授权跳转 URL（admin 配置自检用；登录页经公开 config 判断显示入口）。"""
    cfg = await get_config(session)
    if not cfg["oidc_enabled"] or not cfg["oidc_issuer"]:
        raise BizError(CODE_VALIDATION, t("err.oidc_not_configured"), 404)
    from app.core.security import create_signed_token

    state = create_signed_token(
        {"sub": "oidc"}, token_type="oidc-state", expires_delta=timedelta(minutes=10)
    )
    base = cfg["oidc_issuer"].rstrip("/")
    sep = "&" if "?" in base else "?"
    authorize_url = (
        f"{base}{sep}response_type=code&client_id={cfg['oidc_client_id']}"
        f"&state={state}&scope=openid"
    )
    return ok({"authorize_url": authorize_url, "state": state})


class OidcCallbackBody(BaseModel):
    code: str
    redirect_uri: str = ""


@router.post("/auth/oidc/callback")
async def oidc_callback(
    body: OidcCallbackBody, session: AsyncSession = Depends(get_session)
):
    """OIDC 回调：code 换 token → userinfo → 用户映射（自动开通 role=user）。"""
    import secrets as _secrets

    cfg = await get_config(session)
    if not cfg["oidc_enabled"] or not cfg["oidc_issuer"]:
        raise BizError(CODE_VALIDATION, t("err.oidc_not_configured"), 404)
    base = cfg["oidc_issuer"].rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_resp = await client.post(
                f"{base}/token",
                data={
                    "grant_type": "authorization_code",
                    "code": body.code,
                    "client_id": cfg["oidc_client_id"],
                    "client_secret": cfg["oidc_client_secret"],
                },
            )
            token_resp.raise_for_status()
            access = token_resp.json().get("access_token", "")
            userinfo_resp = await client.get(
                f"{base}/userinfo", headers={"Authorization": f"Bearer {access}"}
            )
            userinfo_resp.raise_for_status()
            claims = userinfo_resp.json()
    except httpx.HTTPError as exc:
        raise BizError(CODE_BAD_CREDENTIALS, t("err.oidc_exchange_failed"), 401) from exc

    username = str(claims.get("preferred_username") or claims.get("sub") or "").strip()
    if not username:
        raise BizError(CODE_VALIDATION, t("err.oidc_no_subject"), 401)
    user = (
        await session.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if user is None:  # 自动开通
        user = User(username=username, password_hash=_secrets.token_urlsafe(32), role="user")
        session.add(user)
        await session.commit()
    if not user.is_active:
        raise BizError(CODE_BAD_CREDENTIALS, t("err.account_disabled"), 401)
    return ok(
        {
            "access_token": create_access_token(user.id, user.token_version),
            "refresh_token": create_refresh_token(user.id, user.token_version),
            "user": {"id": user.id, "username": user.username, "role": user.role},
        }
    )


# ---- LDAP 绑定登录（M01-13；P22.1）----


class LdapLoginBody(BaseModel):
    username: str
    password: str


@router.post("/auth/ldap/login")
async def ldap_login(
    body: LdapLoginBody, request: Request, session: AsyncSession = Depends(get_session)
):
    """LDAP 绑定登录（M01-13）：绑定成功 → 查找/自动开通用户 → 签发会话。"""
    cfg = await get_config(session)
    if not cfg["ldap_enabled"] or not cfg["ldap_server"]:
        raise BizError(CODE_VALIDATION, t("err.ldap_not_configured"), 404)
    import ldap3

    bind_dn = cfg["ldap_bind_dn_tpl"].format(
        username=body.username, base_dn=cfg["ldap_base_dn"]
    )
    try:
        server = ldap3.Server(cfg["ldap_server"], get_info=None, connect_timeout=5)
        conn = ldap3.Connection(server, user=bind_dn, password=body.password, auto_bind=True)
    except Exception as exc:
        raise BizError(CODE_BAD_CREDENTIALS, t("err.bad_credentials"), 401) from exc
    try:
        conn.unbind()
    except Exception:
        pass
    user = (
        await session.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    if user is None:  # 自动开通（随机本地密码，登录走 LDAP）
        import secrets as _secrets

        user = User(
            username=body.username,
            password_hash=hash_password(_secrets.token_urlsafe(32)),
            role="user",
            is_active=True,
        )
        session.add(user)
    if not user.is_active:
        raise BizError(CODE_BAD_CREDENTIALS, t("err.account_disabled"), 401)
    await session.commit()
    return ok(
        {
            "access_token": create_access_token(user.id, user.token_version),
            "refresh_token": create_refresh_token(user.id, user.token_version),
            "user": {"id": user.id, "username": user.username, "role": user.role},
        }
    )


def _secrets_token() -> str:
    import secrets as _secrets

    return _secrets.token_urlsafe(32)
