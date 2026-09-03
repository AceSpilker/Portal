"""应用探活服务（M07-1/2/5；dev-plan P6.1/P6.2/P6.4）。

三种探测方式（apps.health_type）：
- http：HTTP GET，2xx/3xx 视为 up；
- tcp：TCP 连接（health_target 为 host:port）；
- keyword：HTTP GET 且响应体包含 health_target 中的关键字
  （target 格式 `url::关键字`；未含 `::` 时以 url 为目标、关键字为空视为 http）。

状态翻转去抖：仅与 app_status 中现行状态不同时才记 probe_events 并更新 since；
相同状态只刷新 checked_at/latency。状态变化写 notifications（P6.4，渠道接入在 P9）。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portal import App
from app.models.probe import AppStatus, Notification, ProbeEvent

PROBE_TIMEOUT = 5.0  # 单次探测超时（秒）
SLOW_MS = 2000  # 超过该延迟记 slow 事件

_WS_CLIENTS: set = set()  # /ws/notify 连接集合（由 api 层维护）


def register_ws(ws) -> None:
    _WS_CLIENTS.add(ws)


def unregister_ws(ws) -> None:
    _WS_CLIENTS.discard(ws)


async def broadcast(event: dict) -> None:
    """向所有 /ws/notify 连接广播事件；发送失败静默移除连接。"""
    for ws in list(_WS_CLIENTS):
        try:
            await ws.send_json(event)
        except Exception:
            _WS_CLIENTS.discard(ws)


async def _probe_http(
    url: str,
    keyword: str | None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[str, int | None, str]:
    start = time.perf_counter()
    try:
        client_kwargs = {"timeout": PROBE_TIMEOUT, "follow_redirects": True}
        if transport is not None:
            client_kwargs["transport"] = transport
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(url)
    except (httpx.HTTPError, OSError):
        return "down", None, "连接失败"
    latency = int((time.perf_counter() - start) * 1000)
    # HTTP 状态码方式：2xx/3xx 视为 up（M07-1）
    if resp.status_code >= 400:
        return "down", latency, f"HTTP {resp.status_code}"
    if keyword and keyword not in resp.text:
        return "down", latency, "关键字未命中"
    return "up", latency, ""


async def _probe_tcp(target: str) -> tuple[str, int | None, str]:
    host, _, port_s = target.rpartition(":")
    if not host or not port_s.isdigit():
        return "down", None, "目标格式应为 host:port"
    start = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, int(port_s)), PROBE_TIMEOUT
        )
    except (asyncio.TimeoutError, OSError):
        return "down", None, "端口连接失败"
    latency = int((time.perf_counter() - start) * 1000)
    writer.close()
    try:
        await writer.wait_closed()
    except (OSError, asyncio.TimeoutError):
        pass
    return "up", latency, ""


async def probe_once(
    app: App, transport: httpx.AsyncBaseTransport | None = None
) -> tuple[str, int | None, str]:
    """按应用配置执行一次探测，返回 (state, latency_ms, message)。"""
    htype = (app.health_type or "").strip()
    target = (app.health_target or "").strip()
    if htype == "tcp":
        return await _probe_tcp(target)
    if htype in ("http", "keyword"):
        # keyword 目标格式：`url::关键字`；仅填 url 时退化为普通 HTTP 探测
        url, _, keyword = target.partition("::")
        if not url:
            return "down", None, "未配置探测地址"
        return await _probe_http(url, keyword if htype == "keyword" else None, transport)
    return "unknown", None, ""


async def apply_result(
    session: AsyncSession, app: App, state: str, latency: int | None, message: str
) -> dict | None:
    """落库：状态翻转才记事件/更新 since，并产生站内通知；返回广播事件（无变化为 None）。"""
    now = datetime.utcnow()
    status = await session.get(AppStatus, app.id)
    prev_state = status.state if status else "unknown"
    changed = status is None or prev_state != state

    if status is None:
        status = AppStatus(
            app_id=app.id, state=state, latency_ms=latency,
            checked_at=now, since=now, message=message,
        )
        await session.merge(status)
    else:
        status.state = state
        status.latency_ms = latency
        status.checked_at = now
        status.message = message
        if changed:
            status.since = now
    await session.commit()

    if not changed:
        return None

    await session.merge(ProbeEvent(app_id=app.id, event=state, latency_ms=latency))
    level = "error" if state == "down" else "info"
    title = f"{app.name} 已恢复" if state == "up" else f"{app.name} 已下线"
    dedup = f"app-{state}-{app.id}-{now.strftime('%Y%m%d%H%M')}"
    session.add(
        Notification(title=title, body=message, level=level, source="probe", dedup_key=dedup)
    )
    await session.commit()
    return {
        "type": "app_status",
        "data": {"app_id": app.id, "state": state, "latency": latency, "message": message},
    }


async def check_app(session: AsyncSession, app_id: int) -> dict | None:
    """立即探活指定应用并落库（POST /apps/{id}/check）。返回广播事件或 None。"""
    app = await session.get(App, app_id)
    if app is None or app.deleted:
        return None
    state, latency, message = await probe_once(app)
    return await apply_result(session, app, state, latency, message)


async def run_due_checks(session: AsyncSession, tick: int = 10) -> list[dict]:
    """调度任务（每 tick=10s 醒来）：对到期的应用逐个探活，返回广播事件列表。"""
    apps = list(
        (
            await session.execute(
                select(App).where(App.enabled.is_(True), App.deleted == 0)
            )
        ).scalars()
    )
    events: list[dict] = []
    now = time.time()
    for app in apps:
        htype = (app.health_type or "").strip()
        if not htype:
            continue
        interval = max(10, app.health_interval or 60)
        status = await session.get(AppStatus, app.id)
        if status is not None:
            age = now - status.checked_at.timestamp()
            if age < interval - tick / 2:
                continue
        state, latency, message = await probe_once(app)
        event = await apply_result(session, app, state, latency, message)
        if event:
            events.append(event)
    return events
