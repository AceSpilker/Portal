"""工具箱接口（M10-1/3/5；dev-plan 7.3）。权限：A（任意登录用户，权限矩阵工具箱行）。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.response import CODE_VALIDATION, BizError, ok
from app.db.session import get_session
from app.models.tools import WolTarget
from app.models.user import User
from app.services.tools import check_tcp_port, normalize_mac, send_wol

router = APIRouter()


class WolRequest(BaseModel):
    mac: str
    port: int = Field(default=9, ge=1, le=65535)


class PortCheckRequest(BaseModel):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)


class WolTargetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    mac: str
    note: str = Field(default="", max_length=256)


@router.post("/tools/wol")
async def wol_send(
    body: WolRequest,
    _: User = Depends(get_current_user),
):
    """网络唤醒（M10-1）：向局域网广播魔术包。"""
    try:
        sent = send_wol(body.mac, body.port)
    except ValueError:
        raise BizError(CODE_VALIDATION, "MAC 地址格式不正确", 422)
    return ok({"sent_bytes": sent})


@router.post("/tools/port-check")
async def port_check(
    body: PortCheckRequest,
    _: User = Depends(get_current_user),
):
    """TCP 端口连通测试（M10-3）：从服务端发起连接，返回通断与延迟。"""
    result = await asyncio.to_thread(check_tcp_port, body.host, body.port)
    return ok(result)


@router.get("/tools/wol-targets")
async def wol_targets_list(
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    rows = (await session.execute(select(WolTarget).order_by(WolTarget.id))).scalars().all()
    return ok(
        [{"id": t.id, "name": t.name, "mac": t.mac, "note": t.note or ""} for t in rows]
    )


@router.post("/tools/wol-targets")
async def wol_targets_create(
    body: WolTargetCreate,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    try:
        mac = normalize_mac(body.mac)
    except ValueError:
        raise BizError(CODE_VALIDATION, "MAC 地址格式不正确", 422)
    t = WolTarget(name=body.name, mac=mac, note=body.note)
    session.add(t)
    await session.commit()
    return ok({"id": t.id, "name": t.name, "mac": t.mac, "note": t.note})


@router.delete("/tools/wol-targets/{target_id}")
async def wol_targets_delete(
    target_id: int,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    t = await session.get(WolTarget, target_id)
    if t:
        await session.delete(t)
        await session.commit()
    return True
