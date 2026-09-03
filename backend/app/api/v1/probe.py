"""探活接口（M07-1/2；dev-plan P6.3/P6.4；api-spec §4.2/§5）。

- POST /apps/{id}/check：立即探活一次（A）；
- GET /probe/status：全部应用当前状态（A，首页磁贴初始加载）；
- GET /public/apps：访客首页数据（P7.5）；
- 站内通知（/notifications…）自 P9 起迁移至 api/v1/notify.py；
- WS /ws/notify：状态变化广播（登录用户），挂在应用根路径（同 /ws/monitor）。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.response import ok
from app.core.security import decode_token
from app.db.session import SessionLocal, get_session
from app.models.portal import App
from app.models.probe import AppStatus, ProbeEvent
from app.models.user import User
from app.services import probe
from app.services.wsbus import broadcast, register_ws, unregister_ws

router = APIRouter()


@router.post("/apps/{app_id}/check")
async def check_app_now(
    app_id: int,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """立即探活一次（M07-1；api-spec §4.2 P6）。"""
    event = await probe.check_app(session, app_id)
    if event is None:
        status = await session.get(AppStatus, app_id)
        latency = status.latency_ms if status else None
        return ok({"state": status.state if status else "unknown", "latency_ms": latency})
    if event["data"]["state"] == "up":
        return ok({"state": "up", "latency_ms": event["data"]["latency"]})
    return ok({"state": "down", "latency_ms": event["data"]["latency"]})


@router.get("/probe/status")
async def probe_status(
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """全部应用当前状态（首页磁贴初始加载；M07-2）。"""
    rows = (await session.execute(select(AppStatus))).scalars().all()
    return ok(
        {
            str(r.app_id): {
                "state": r.state,
                "latency_ms": r.latency_ms,
                "message": r.message or "",
            }
            for r in rows
        }
    )


@router.get("/public/apps")
async def public_apps(session: AsyncSession = Depends(get_session)):
    """访客首页数据（M01-10；P7.5）：免认证，仅 visibility=public 的启用应用。

    设置键 guest.enabled=0（默认）时返回 404。
    """
    from app.models.setting import Setting

    row = await session.get(Setting, "guest.enabled")
    enabled = bool(json.loads(row.value)) if row else False
    if not enabled:
        from app.core.i18n import t as _t
        from app.core.response import CODE_NOT_FOUND, fail

        return fail(CODE_NOT_FOUND, _t("err.guest_disabled"), 404)
    apps = (
        await session.execute(
            select(App)
            .where(App.deleted.is_(False), App.enabled.is_(True), App.visibility == "public")
            .order_by(App.sort, App.id)
        )
    ).scalars()
    return ok(
        [
            {"id": a.id, "name": a.name, "icon": a.icon, "icon_type": a.icon_type}
            for a in apps
        ]
    )


async def notify_ws(websocket: WebSocket) -> None:
    """WS /ws/notify（P6.3）：登录用户接收 app_status / notification 广播。"""
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
    register_ws(websocket)
    try:
        while True:
            await websocket.receive_text()  # 保活；客户端消息忽略
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        unregister_ws(websocket)


async def probe_job() -> None:
    """调度任务（每 10s 醒来）：对到期应用探活并广播状态变化。"""
    async with SessionLocal() as session:
        events = await probe.run_due_checks(session)
    for ev in events:
        await broadcast(ev)


@router.get("/probe/availability")
async def probe_availability(
    range_: str = Query("24h", alias="range"),
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """可用性分析（M07-3/4；P10.4）：各应用 24h/7d/30d 可用率 + 最近事件时间线。

    口径：窗口起点状态由 app_status（state/since）推断，since 晚于窗口起点则
    从首个事件起算；down 时长占比即不可用率，unknown 不计损。
    """
    from datetime import datetime, timedelta

    ranges = {"24h": 24 * 3600, "7d": 7 * 86400, "30d": 30 * 86400}
    if range_ not in ranges:
        from app.core.i18n import t as _t
        from app.core.response import CODE_VALIDATION, fail

        return fail(CODE_VALIDATION, _t("err.invalid_metric_or_range"), 422)
    end = datetime.utcnow()
    start = end - timedelta(seconds=ranges[range_])

    apps = (
        await session.execute(select(App).where(App.deleted.is_(False), App.enabled.is_(True)))
    ).scalars().all()
    result = []
    for app in apps:
        status = await session.get(AppStatus, app.id)
        events = (
            await session.execute(
                select(ProbeEvent)
                .where(ProbeEvent.app_id == app.id, ProbeEvent.created_at >= start)
                .order_by(ProbeEvent.created_at)
            )
        ).scalars().all()
        # 窗口起点状态：since 早于起点 → 沿用当前状态；否则 unknown（不计损）
        cur = None
        if status is not None and status.since <= start:
            cur = status.state
        down = 0.0
        last_t = start
        for ev in events:
            if cur == "down":
                down += (ev.created_at - last_t).total_seconds()
            cur = ev.event if ev.event in ("up", "down") else cur
            last_t = ev.created_at
        if cur == "down":
            down += (end - last_t).total_seconds()
        total = ranges[range_]
        uptime_pct = None if cur is None else round(max(0.0, (total - down) / total * 100), 2)
        result.append(
            {
                "app_id": app.id,
                "name": app.name,
                "uptime_pct": uptime_pct,
                "current_state": status.state if status else "unknown",
                "event_count": len(events),
            }
        )
    recent = (
        await session.execute(
            select(ProbeEvent).order_by(ProbeEvent.id.desc()).limit(30)
        )
    ).scalars().all()
    names = {a.id: a.name for a in apps}
    return ok(
        {
            "range": range_,
            "apps": result,
            "timeline": [
                {
                    "app_id": e.app_id,
                    "app_name": names.get(e.app_id, f"#{e.app_id}"),
                    "event": e.event,
                    "latency_ms": e.latency_ms,
                    "created_at": e.created_at.isoformat() + "Z",
                }
                for e in reversed(recent)
            ],
        }
    )
