"""SSH 隧道接口（M04-16；dev-plan P20.1/P20.2；api-spec §4.5）。

- 凭据 CRUD（secret Fernet 加密存储，回传脱敏）；
- 隧道 CRUD + start/stop（本机端口自动分配）+ open-url（短时签名直达链接）。
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.core.i18n import t
from app.core.response import CODE_NOT_FOUND, CODE_VALIDATION, BizError, ok
from app.core.secret_box import encrypt_secret
from app.core.security import create_signed_token
from app.db.session import get_session
from app.models.tunnel import SSHCredential, Tunnel
from app.models.user import User
from app.services import tunnel_svc

router = APIRouter()

TUNNEL_TOKEN_TTL = 1800  # 直链有效期 30 分钟


# ---- 凭据 ----


class CredentialBody(BaseModel):
    name: str = Field(max_length=60)
    host: str
    port: int = Field(default=22, ge=1, le=65535)
    username: str = "root"
    password: str = ""
    private_key: str = ""
    note: str = ""


@router.get("/ssh-credentials")
async def list_credentials(
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    rows = (await session.execute(select(SSHCredential).order_by(SSHCredential.id))).scalars().all()
    return ok([await tunnel_svc.credential_secret_masked(c) for c in rows])


@router.post("/ssh-credentials")
async def create_credential(
    body: CredentialBody,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    if not body.password and not body.private_key:
        raise BizError(CODE_VALIDATION, t("v.credential_secret_required"), 422)
    secret = body.private_key if body.private_key else body.password
    c = SSHCredential(
        name=body.name, host=body.host, port=body.port, username=body.username,
        secret=encrypt_secret(secret), note=body.note,
    )
    session.add(c)
    await session.commit()
    return ok(await tunnel_svc.credential_secret_masked(c), t("ok.saved"))


@router.delete("/ssh-credentials/{cred_id}")
async def delete_credential(
    cred_id: int, _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    c = await session.get(SSHCredential, cred_id)
    if c is None:
        raise BizError(CODE_NOT_FOUND, t("err.credential_not_found"), 404)
    await session.delete(c)
    await session.commit()
    return ok({"id": cred_id}, t("ok.deleted"))


# ---- 隧道 ----


def _tunnel_view(t: Tunnel) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "credential_id": t.credential_id,
        "remote_host": t.remote_host,
        "remote_port": t.remote_port,
        "local_port": t.local_port,
        "auto_close_min": t.auto_close_min,
        "status": t.status,
        "last_error": t.last_error,
        "last_active_at": t.last_active_at.isoformat() + "Z" if t.last_active_at else None,
    }


class TunnelBody(BaseModel):
    name: str = Field(max_length=60)
    credential_id: int
    remote_host: str = "127.0.0.1"
    remote_port: int = Field(ge=1, le=65535)
    local_port: int = Field(default=0, ge=0, le=65535)
    auto_close_min: int = Field(default=30, ge=0, le=1440)


@router.get("/tunnels")
async def list_tunnels(
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    rows = (await session.execute(select(Tunnel).order_by(Tunnel.id))).scalars().all()
    return ok([_tunnel_view(t) for t in rows])


@router.post("/tunnels")
async def create_tunnel(
    body: TunnelBody, _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    tun = Tunnel(
        name=body.name, credential_id=body.credential_id,
        remote_host=body.remote_host, remote_port=body.remote_port,
        local_port=body.local_port, auto_close_min=body.auto_close_min,
    )
    session.add(tun)
    await session.commit()
    return ok(_tunnel_view(tun), t("ok.saved"))


async def _tunnel_or_404(session: AsyncSession, tunnel_id: int) -> Tunnel:
    t = await session.get(Tunnel, tunnel_id)
    if t is None:
        raise BizError(CODE_NOT_FOUND, t("err.tunnel_not_found"), 404)
    return t


@router.post("/tunnels/{tunnel_id}/start")
async def start_tunnel(
    tunnel_id: int, _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    """启动隧道：SSH 连接 + 本地转发（端口 0=自动分配空闲端口）。"""
    tun = await _tunnel_or_404(session, tunnel_id)
    if tun.status == "running" and tunnel_svc.get_handle(tun.id) is not None:
        return ok(_tunnel_view(tun), t("ok.tunnel_running"))
    try:
        await tunnel_svc.start_tunnel(session, tun)
    except Exception as exc:  # noqa: BLE001 —— 连接失败转业务错误
        message = str(exc) or getattr(exc, "message", "") or type(exc).__name__
        tun.status = "error"
        tun.last_error = message[:300]
        await session.commit()
        raise BizError(
            CODE_VALIDATION, t("err.tunnel_start_failed", reason=message[:160]), 422
        ) from exc
    return ok(_tunnel_view(tun), t("ok.tunnel_started"))


@router.post("/tunnels/{tunnel_id}/stop")
async def stop_tunnel(
    tunnel_id: int, _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    tun = await _tunnel_or_404(session, tunnel_id)
    await tunnel_svc.stop_tunnel(session, tun)
    return ok(_tunnel_view(tun), t("ok.tunnel_stopped"))


@router.delete("/tunnels/{tunnel_id}")
async def delete_tunnel(
    tunnel_id: int, _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    tun = await _tunnel_or_404(session, tunnel_id)
    if tun.status == "running":
        await tunnel_svc.stop_tunnel(session, tun)
    await session.delete(tun)
    await session.commit()
    return ok({"id": tunnel_id}, t("ok.deleted"))


@router.get("/tunnels/{tunnel_id}/open-url")
async def tunnel_open_url(
    tunnel_id: int, _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    """直达链接（P20.2）：短时签名 token 的 /tunnel/{id}?t=…（新标签打开）。"""
    tun = await _tunnel_or_404(session, tunnel_id)
    if tun.status != "running":
        raise BizError(CODE_VALIDATION, t("err.tunnel_not_running"), 422)
    token = create_signed_token(
        {"tid": tun.id, "kind": "tunnel"},
        token_type="tunnel",
        expires_delta=timedelta(seconds=TUNNEL_TOKEN_TTL),
    )
    return ok({"url": f"/tunnel/{tun.id}?t={token}", "expires_in": TUNNEL_TOKEN_TTL})
