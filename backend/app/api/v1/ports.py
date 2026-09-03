"""端口监控接口（M18-1~5/7；dev-plan P11；api-spec §4.5）。

- GET /ports/listen：监听清单（A）；
- GET /ports/lookup?port=：占用检索（A）；
- GET /ports/monitors（A 读）/ POST、PUT/DELETE /{id}（M 写）；
- POST /ports/monitors/import：批量导入 host:port（M，去重）；
- GET /ports/monitors/{id}/events · GET /ports/events：事件流水（A）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_admin
from app.core.i18n import t
from app.core.response import CODE_NOT_FOUND, CODE_VALIDATION, BizError, ok
from app.db.session import SessionLocal, get_session
from app.models.port import PortMonitor
from app.models.portal import App
from app.models.user import User
from app.services import ports

router = APIRouter()


def _monitor_view(m: PortMonitor, app_name: str | None = None) -> dict:
    return {
        "id": m.id,
        "name": m.name,
        "host": m.host,
        "port": m.port,
        "app_id": m.app_id,
        "app_name": app_name,
        "interval": m.interval,
        "enabled": bool(m.enabled),
        "state": m.state,
        "last_latency_ms": m.last_latency_ms,
        "last_checked_at": m.last_checked_at.isoformat() + "Z" if m.last_checked_at else None,
    }


async def _monitors_with_apps(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(select(PortMonitor).order_by(PortMonitor.id))).scalars().all()
    app_ids = {m.app_id for m in rows if m.app_id}
    apps: dict[int, str] = {}
    if app_ids:
        for a in (await session.execute(select(App).where(App.id.in_(app_ids)))).scalars().all():
            apps[a.id] = a.name
    return [_monitor_view(m, apps.get(m.app_id)) for m in rows]


@router.get("/ports/listen")
async def ports_listen(_: User = Depends(get_current_user)):
    """当前监听清单（M18-1；非 root 下他进程名可能不可见，以 - 兜底）。"""
    import asyncio

    return ok(await asyncio.to_thread(ports.listen_list))


@router.get("/ports/lookup")
async def ports_lookup(
    port: int = Query(ge=1, le=65535),
    _: User = Depends(get_current_user),
):
    """端口占用检索（M18-5）：占用进程/命令行/用户。"""
    import asyncio

    return ok(await asyncio.to_thread(ports.lookup_port, port))


@router.get("/ports/monitors")
async def list_monitors(
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return ok(await _monitors_with_apps(session))


class MonitorIn(BaseModel):
    name: str = ""
    host: str = "127.0.0.1"
    port: int = Field(ge=1, le=65535)
    app_id: int | None = None
    interval: int = Field(60, ge=10, le=86400)
    enabled: bool = True


async def _monitor_or_404(session: AsyncSession, monitor_id: int) -> PortMonitor:
    m = await session.get(PortMonitor, monitor_id)
    if m is None:
        raise BizError(CODE_NOT_FOUND, t("err.port_monitor_not_found"), 404)
    return m


@router.post("/ports/monitors")
async def create_monitor(
    body: MonitorIn,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    if body.app_id is not None:
        if await session.get(App, body.app_id) is None:
            raise BizError(CODE_VALIDATION, t("err.app_not_found"), 422)
    m = PortMonitor(
        name=body.name, host=body.host, port=body.port, app_id=body.app_id,
        interval=body.interval, enabled=int(body.enabled),
    )
    session.add(m)
    await session.commit()
    return ok(_monitor_view(m))


@router.put("/ports/monitors/{monitor_id}")
async def update_monitor(
    monitor_id: int,
    body: MonitorIn,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    m = await _monitor_or_404(session, monitor_id)
    m.name = body.name
    m.host = body.host
    m.port = body.port
    m.app_id = body.app_id
    m.interval = body.interval
    m.enabled = int(body.enabled)
    await session.commit()
    return ok(_monitor_view(m))


@router.delete("/ports/monitors/{monitor_id}")
async def delete_monitor(
    monitor_id: int,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    m = await _monitor_or_404(session, monitor_id)
    await session.delete(m)
    await session.commit()
    return ok(True)


class ImportIn(BaseModel):
    items: list[str] = Field(min_length=1, max_length=200)  # 每行 host:port 或 name|host:port


@router.post("/ports/monitors/import")
async def import_monitors(
    body: ImportIn,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """批量导入（M18-6）：每行 `host:port` 或 `名称|host:port`；同 host+port 去重。"""
    existing = {
        (m.host, m.port)
        for m in (await session.execute(select(PortMonitor))).scalars().all()
    }
    created, skipped = 0, 0
    for line in body.items:
        line = line.strip()
        if not line:
            continue
        name = ""
        if "|" in line:
            name, line = line.split("|", 1)
            name = name.strip()
        host, _, port_s = line.rpartition(":")
        host = host.strip() or "127.0.0.1"
        if not port_s.isdigit() or not 1 <= int(port_s) <= 65535:
            raise BizError(CODE_VALIDATION, t("err.port_import_line"), 422)
        port = int(port_s)
        if (host, port) in existing:
            skipped += 1
            continue
        existing.add((host, port))
        session.add(PortMonitor(name=name, host=host, port=port))
        created += 1
    await session.commit()
    return ok({"created": created, "skipped": skipped})


@router.get("/ports/monitors/{monitor_id}/events")
async def monitor_events(
    monitor_id: int,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _monitor_or_404(session, monitor_id)
    return ok(await ports.events_with_names(session, monitor_id))


@router.get("/ports/events")
async def all_events(
    limit: int = Query(50, ge=1, le=200),
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return ok(await ports.events_with_names(session, None, limit))


async def ports_job() -> None:
    """调度任务（每 10s）：端口监控项巡检，翻转事件经 WS 广播。"""
    from app.services.wsbus import broadcast

    async with SessionLocal() as session:
        events = await ports.run_due_checks(session)
    for ev in events:
        await broadcast(ev)
