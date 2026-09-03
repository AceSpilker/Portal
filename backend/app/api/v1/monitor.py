"""监控接口（M17-6/8/9；dev-plan P5.3/P5.4；api-spec §4.4/§5）。

权限：A（任意登录用户）——权限矩阵 §3 规定 user 可查看基础资源图；
进程/Docker/告警等增强接口（M2）仍为 M。WS /ws/monitor 挂在应用根路径
（/api 之外），query 带 access token 鉴权；传输加密中间件只处理 http scope，
WS 明文穿透（与静态资源同属豁免面）。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.i18n import t
from app.core.response import CODE_VALIDATION, BizError, ok
from app.core.security import decode_token
from app.db.session import SessionLocal, get_session
from app.models.user import User
from app.services import monitor
from app.services.monitor import HISTORY_METRICS, RANGE_SECONDS, build_history, collect_overview

router = APIRouter()


@router.get("/monitor/system")
async def monitor_system(_: User = Depends(get_current_user)):
    """实时概览（M17-1~5）：系统信息/CPU/内存/磁盘/网络（含速率与当日流量）。"""
    return ok(collect_overview(monitor.ws_net_calc))


@router.get("/monitor/history")
async def monitor_history(
    metric: str = Query("cpu"),
    range_: str = Query("24h", alias="range"),
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """历史曲线（M17-6）：metric ∈ cpu/mem/disk/net，range ∈ 24h/7d/30d。"""
    if metric not in HISTORY_METRICS or range_ not in RANGE_SECONDS:
        raise BizError(CODE_VALIDATION, t("err.invalid_metric_or_range"), 422)
    return ok(await build_history(session, metric, range_))


async def monitor_ws(websocket: WebSocket) -> None:
    """WS /ws/monitor（M17-8）：管理员鉴权后每 2 秒推送实时概览。"""
    try:
        payload = decode_token(websocket.query_params.get("token", ""), "access")
        async with SessionLocal() as session:
            user = await session.get(User, int(payload["sub"]))
        if user is None or not user.is_active:
            raise ValueError("inactive")
    except Exception:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    try:
        while True:
            data = collect_overview(monitor.ws_net_calc)
            await websocket.send_json({"type": "monitor", "data": data})
            # 推送间隔可配（monitor.push_interval，每次循环读取即时生效）
            async with SessionLocal() as session:
                push_interval = await monitor.read_push_interval(session)
            await asyncio.sleep(max(1, push_interval))
    except (WebSocketDisconnect, RuntimeError):
        return


async def sampler_job() -> None:
    """采样任务（P5.2）：每 10s 醒来一次，达到 monitor.sample_interval 才落一行。"""
    async with SessionLocal() as session:
        if await monitor.should_sample(session):
            await monitor.sample_once(session)


async def cleanup_job() -> None:
    """APScheduler 每小时清理任务：按 monitor.retention_days 删过期采样。"""
    async with SessionLocal() as session:
        await monitor.cleanup_expired(session)
