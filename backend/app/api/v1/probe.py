"""探活与站内通知接口（M07-2/5；dev-plan P6.3/P6.4；api-spec §4.2/§5）。

- POST /apps/{id}/check：立即探活一次（A）；
- GET /probe/status：全部应用当前状态（A，首页磁贴初始加载）；
- GET /notifications · PUT /notifications/{id}/read：站内通知最小集（A，P6.4；
  完整通知中心在 P9）；
- WS /ws/notify：状态变化广播（登录用户），挂在应用根路径（同 /ws/monitor）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.response import ok
from app.core.security import decode_token
from app.db.session import SessionLocal, get_session
from app.models.probe import AppStatus, Notification
from app.models.user import User
from app.services import probe

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


class StatusBroadcast(BaseModel):
    data: dict


@router.get("/notifications")
async def list_notifications(
    unread: int | None = Query(None),
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """站内通知（P6.4 最小集；完整通知中心 P9）。"""
    stmt = select(Notification).order_by(Notification.id.desc()).limit(50)
    if unread:
        stmt = stmt.where(Notification.is_read == 0)
    rows = (await session.execute(stmt)).scalars().all()
    return ok(
        [
        {
            "id": n.id,
            "title": n.title,
            "body": n.body,
            "level": n.level,
            "source": n.source,
            "is_read": bool(n.is_read),
            "created_at": n.created_at.isoformat() + "Z",
        }
            for n in rows
        ]
    )


@router.put("/notifications/{notification_id}/read")
async def mark_read(
    notification_id: int,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    n = await session.get(Notification, notification_id)
    if n:
        n.is_read = 1
        await session.commit()
    return ok(True)


async def notify_ws(websocket: WebSocket) -> None:
    """WS /ws/notify（P6.3）：登录用户接收 app_status 变化广播。"""
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
    probe.register_ws(websocket)
    try:
        while True:
            await websocket.receive_text()  # 保活；客户端消息忽略
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        probe.unregister_ws(websocket)


async def probe_job() -> None:
    """调度任务（每 10s 醒来）：对到期应用探活并广播状态变化。"""
    async with SessionLocal() as session:
        events = await probe.run_due_checks(session)
    for ev in events:
        await probe.broadcast(ev)
