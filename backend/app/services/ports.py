"""端口监控服务（M18；dev-plan P11；api-spec §3.5/§4.5）。

- listen_list()/lookup_port()：优先 psutil.net_connections；macOS 非 root
  整表权限会抛 PermissionError，按 CLAUDE.md 多平台约定回退系统 lsof 解析；
  进程信息不可见时以 "-" 兜底；
- 状态机：探测到期的监控项，状态翻转才记 port_events 并 dispatch
  port_down/port_up 事件（P9 通知出口；Flow 联动 P14 接入）。
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from datetime import datetime

import psutil
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.port import PortEvent, PortMonitor
from app.models.portal import App
from app.services import notify

PORT_PROBE_TIMEOUT = 3.0
_SLOW_MS = 1000


def _proc_info(pid: int | None) -> tuple[str, str]:
    """(进程名, 命令行截断)；权限不足/进程消失以 - 兜底（macOS 非 root 常见）。"""
    if not pid:
        return "-", ""
    try:
        p = psutil.Process(pid)
        return p.name(), " ".join(p.cmdline())[:120]
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return "-", ""


def _listen_via_lsof() -> list[dict] | None:
    """macOS 非 root 回退：psutil 整表权限不足时用系统 lsof 解析 LISTEN。"""
    try:
        out = subprocess.run(
            ["lsof", "-nP", "-i", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    rows: dict[tuple, dict] = {}
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 9:
            continue
        command, pid_s, _user, _fd, _typ, _dev, _off, node, name = parts[:9]
        if node != "TCP" or ":" not in name:
            continue
        addr, _, port_s = name.rpartition(":")
        if not port_s.isdigit():
            continue
        pid = int(pid_s) if pid_s.isdigit() else None
        key = (addr, port_s)
        if key in rows:
            continue
        proc, cmdline = _proc_info(pid)
        rows[key] = {
            "proto": "tcp",
            "addr": "0.0.0.0" if addr == "*" else addr,
            "port": int(port_s),
            "pid": pid,
            "proc": proc if proc != "-" else command,
            "cmdline": cmdline,
        }
    return list(rows.values())


def listen_list() -> list[dict]:
    """当前监听清单（M18-1）：协议/地址/端口/进程名/命令行截断。"""
    rows = []
    try:
        for c in psutil.net_connections(kind="inet"):
            if c.status != psutil.CONN_LISTEN:
                continue
            laddr = c.laddr
            proc_name, cmdline = _proc_info(c.pid)
            rows.append(
                {
                    "proto": "tcp" if c.type == psutil.SOCK_STREAM else "udp",
                    "addr": laddr.ip if laddr else "",
                    "port": laddr.port if laddr else 0,
                    "pid": c.pid or None,
                    "proc": proc_name,
                    "cmdline": cmdline,
                }
            )
    except (psutil.AccessDenied, PermissionError):
        fallback = _listen_via_lsof()
        if fallback is not None:
            rows = fallback
    rows.sort(key=lambda r: (r["proto"], r["port"]))
    return rows


def _lookup_via_lsof(port: int) -> list[dict] | None:
    """macOS 非 root 回退：lsof 按端口检索。"""
    try:
        out = subprocess.run(
            ["lsof", "-nP", "-i", f":{port}"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    seen: set[tuple] = set()
    result = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 9:
            continue
        command, pid_s, username, _fd, _typ, _dev, _off, node, name = parts[:9]
        if node not in ("TCP", "UDP") or ":" not in name:
            continue
        addr, _, port_s = name.rpartition(":")
        if not port_s.isdigit() or int(port_s) != port:
            continue
        pid = int(pid_s) if pid_s.isdigit() else None
        key = (node, addr, pid)
        if key in seen:
            seen.add(key)
            continue
        seen.add(key)
        proc, cmdline = _proc_info(pid)
        result.append(
            {
                "proto": node.lower(),
                "addr": "0.0.0.0" if addr == "*" else addr,
                "port": port,
                "status": "LISTEN" if "LISTEN" in line else "ESTABLISHED",
                "pid": pid,
                "proc": proc if proc != "-" else command,
                "cmdline": cmdline,
                "username": username,
            }
        )
    return result


def lookup_port(port: int) -> list[dict]:
    """端口占用检索（M18-5）：返回占用该端口的进程与命令行。"""
    result = []
    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, PermissionError):
        fallback = _lookup_via_lsof(port)
        return fallback if fallback is not None else []
    for c in conns:
        if not c.laddr or c.laddr.port != port:
            continue
        proc_name, cmdline, username = "-", "", ""
        if c.pid:
            try:
                p = psutil.Process(c.pid)
                proc_name = p.name()
                cmdline = " ".join(p.cmdline())[:160]
                username = p.username()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        result.append(
            {
                "proto": "tcp" if c.type == psutil.SOCK_STREAM else "udp",
                "addr": c.laddr.ip,
                "port": c.laddr.port,
                "status": c.status,
                "pid": c.pid,
                "proc": proc_name,
                "cmdline": cmdline,
                "username": username,
            }
        )
    # 去重（同进程多连接）
    seen: set[tuple] = set()
    unique = []
    for r in result:
        key = (r["proto"], r["addr"], r["status"], r["pid"], r["proc"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


async def probe_port(host: str, port: int) -> tuple[str, int | None]:
    """TCP 探测：返回 (state, latency_ms)。"""
    start = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), PORT_PROBE_TIMEOUT
        )
    except (asyncio.TimeoutError, OSError):
        return "down", None
    latency = int((time.perf_counter() - start) * 1000)
    writer.close()
    try:
        await writer.wait_closed()
    except (OSError, asyncio.TimeoutError):
        pass
    return "up", latency


async def apply_result(
    session: AsyncSession, m: PortMonitor, state: str, latency: int | None
) -> dict | None:
    """落库：翻转才记事件/更新 since 语义字段，并 dispatch port_down/port_up。

    P20.3：每次探测同时落 port_probe_samples（延迟曲线）。
    """
    from app.models.port import PortProbeSample

    prev = m.state
    changed = prev != state
    m.state = state
    m.last_latency_ms = latency
    m.last_checked_at = datetime.utcnow()
    session.add(PortProbeSample(monitor_id=m.id, state=state, latency_ms=latency))
    await session.commit()

    if not changed:
        return None

    await session.merge(PortEvent(monitor_id=m.id, event=state, latency_ms=latency))
    await session.commit()
    name = m.name or f"{m.host}:{m.port}"
    body = f"{m.host}:{m.port}"
    if state == "up" and latency is not None:
        body += f" · {latency}ms"
    await notify.dispatch(
        session,
        event="port_down" if state == "down" else "port_up",
        source="port",
        title=f"端口 {name} {'已恢复' if state == 'up' else '不可达'}",
        body=body,
        level="info" if state == "up" else "warn",
        dedup_key=f"port-{state}-{m.id}-{datetime.utcnow().strftime('%Y%m%d%H%M')}",
    )
    return {
        "type": "port_status",
        "data": {"monitor_id": m.id, "name": name, "state": state, "latency": latency},
    }


async def check_monitor(session: AsyncSession, monitor_id: int) -> dict | None:
    m = await session.get(PortMonitor, monitor_id)
    if m is None or not m.enabled:
        return None
    state, latency = await probe_port(m.host, m.port)
    return await apply_result(session, m, state, latency)


async def run_due_checks(session: AsyncSession, tick: int = 10) -> list[dict]:
    """调度任务（每 tick=10s）：对到期的监控项逐个探测，返回广播事件。"""
    monitors = (
        await session.execute(select(PortMonitor).where(PortMonitor.enabled.is_(True)))
    ).scalars().all()
    events: list[dict] = []
    now = time.time()
    for m in monitors:
        interval = max(10, m.interval or 60)
        if m.last_checked_at is not None:
            age = now - m.last_checked_at.timestamp()
            if age < interval - tick / 2:
                continue
        state, latency = await probe_port(m.host, m.port)
        ev = await apply_result(session, m, state, latency)
        if ev:
            events.append(ev)
    return events


async def events_with_names(
    session: AsyncSession, monitor_id: int | None = None, limit: int = 50
) -> list[dict]:
    """事件流水（可按监控项过滤），附带监控项与应用名。"""
    stmt = select(PortEvent).order_by(PortEvent.id.desc()).limit(limit)
    if monitor_id:
        stmt = stmt.where(PortEvent.monitor_id == monitor_id)
    rows = (await session.execute(stmt)).scalars().all()
    monitors = {
        m.id: m for m in (
            await session.execute(select(PortMonitor))
        ).scalars().all()
    }
    app_ids = {m.app_id for m in monitors.values() if m.app_id}
    apps: dict[int, str] = {}
    if app_ids:
        for a in (
            await session.execute(select(App).where(App.id.in_(app_ids)))
        ).scalars().all():
            apps[a.id] = a.name
    out = []
    for e in rows:
        m = monitors.get(e.monitor_id)
        out.append(
            {
                "id": e.id,
                "monitor_id": e.monitor_id,
                "monitor_name": (m.name or f"{m.host}:{m.port}") if m else f"#{e.monitor_id}",
                "app_id": m.app_id if m else None,
                "app_name": apps.get(m.app_id) if m and m.app_id else None,
                "event": e.event,
                "latency_ms": e.latency_ms,
                "created_at": e.created_at.isoformat() + "Z",
            }
        )
    return out


# ---------- 端口进阶（M18-8~12；dev-plan P20.3） ----------

SAMPLE_RETENTION_DAYS = 7
LISTEN_HISTORY_KEEP = 100


async def record_listen_snapshot(session: AsyncSession) -> dict | None:
    """监听快照差异（M18-9）：与上次快照比对，变化记 PortListenHistory。"""
    import json as _json

    from app.models.port import PortListenHistory
    from app.models.setting import Setting

    current = listen_list()
    fp = sorted((f"{e.get('host')}|{e.get('port')}|{e.get('process', '')}" for e in current))
    last = await session.get(Setting, "ports.last_listen")
    last_fp = None
    if last:
        try:
            last_fp = sorted(_json.loads(_json.loads(last.value)))
        except (ValueError, TypeError):
            last_fp = None
    if last_fp == fp:
        return None
    prev_set = set(last_fp or [])
    curr_set = set(fp)

    def _split(item: str):
        host, port, process = item.split("|", 2)
        return {"host": host, "port": int(port) if port.isdigit() else port, "process": process}

    added = [_split(i) for i in sorted(curr_set - prev_set)]
    removed = [_split(i) for i in sorted(prev_set - curr_set)]
    if added or removed:
        session.add(
            PortListenHistory(
                added=_json.dumps(added, ensure_ascii=False),
                removed=_json.dumps(removed, ensure_ascii=False),
            )
        )
        # 只保留最近 LISTEN_HISTORY_KEEP 条
        rows = (
            await session.execute(
                select(PortListenHistory).order_by(PortListenHistory.id.desc()).offset(LISTEN_HISTORY_KEEP)
            )
        ).scalars().all()
        for r in rows:
            await session.delete(r)
        await session.merge(Setting(key="ports.last_listen", value=_json.dumps(fp)))
        await session.commit()
        return {"added": added, "removed": removed}
    await session.merge(Setting(key="ports.last_listen", value=_json.dumps(fp)))
    await session.commit()
    return None


async def listen_history(session: AsyncSession, limit: int = 20) -> list[dict]:
    import json as _json

    from app.models.port import PortListenHistory

    rows = (
        (
            await session.execute(
                select(PortListenHistory).order_by(PortListenHistory.id.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": r.id,
            "added": _json.loads(r.added),
            "removed": _json.loads(r.removed),
            "created_at": r.created_at.isoformat() + "Z",
        }
        for r in rows
    ]


async def exposed_ports(session: AsyncSession) -> list[dict]:
    """裸露端口提示（M18-10）：通配监听且未被任何启用监控项覆盖的端口。"""
    monitors = (
        await session.execute(select(PortMonitor).where(PortMonitor.enabled.is_(True)))
    ).scalars().all()
    watched = {(m.host, m.port) for m in monitors}
    watched_ports = {m.port for m in monitors}
    result = []
    for e in listen_list():
        host = str(e.get("host", ""))
        port = int(e.get("port", 0) or 0)
        if host not in ("0.0.0.0", "::", "*"):
            continue
        # 已被监控项覆盖（同端口任意 host）则不算裸露
        if port in watched_ports:
            continue
        if any(h in ("127.0.0.1", "0.0.0.0", "::") and p == port for h, p in watched):
            continue
        result.append(
            {
                "port": port,
                "process": e.get("process", ""),
                "host": host,
            }
        )
    return result


async def public_reach(session: AsyncSession) -> dict:
    """公网可达性对比（M18-11）：探测公网 IP 对本机启用监控端口的可达性。

    依赖 NAT 回环（hairpin），路由器不支持时公网列恒 false——文档已注明。
    公网 IP 经 stores 缓存 1h。
    """
    import httpx as _httpx

    from app.core.stores import stores

    ip = await stores.store.get("cache:public_ip")
    if not ip:
        try:
            async with _httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get("https://api.ipify.org")
                ip = resp.text.strip()[:64] if resp.status_code == 200 else ""
        except Exception:
            ip = ""
        if ip:
            await stores.store.set("cache:public_ip", ip, ttl=3600)
    monitors = (
        await session.execute(
            select(PortMonitor).where(
                PortMonitor.enabled.is_(True),
                PortMonitor.host.in_(("127.0.0.1", "localhost", "0.0.0.0", "::1")),
            )
        )
    ).scalars().all()
    items = []
    for m in monitors:
        reachable = False
        if ip:
            state, _lat = await probe_port(ip, m.port)
            reachable = state == "up"
        items.append(
            {
                "monitor_id": m.id,
                "name": m.name or f"{m.host}:{m.port}",
                "port": m.port,
                "local_state": m.state,
                "public_reachable": reachable if ip else None,
            }
        )
    return {"public_ip": ip or None, "items": items}


async def port_latency_history(
    session: AsyncSession, monitor_id: int, range_: str = "24h"
) -> dict:
    """端口延迟曲线（M18-8）：port_probe_samples 趋势点。"""
    from datetime import timedelta

    from app.models.port import PortProbeSample

    ranges = {"6h": 6 * 3600, "24h": 24 * 3600, "7d": 7 * 86400}
    if range_ not in ranges:
        ranges[range_] = 24 * 3600
    start = datetime.utcnow() - timedelta(seconds=ranges[range_])
    rows = (
        (
            await session.execute(
                select(PortProbeSample)
                .where(
                    PortProbeSample.monitor_id == monitor_id,
                    PortProbeSample.created_at >= start,
                )
                .order_by(PortProbeSample.created_at)
            )
        )
        .scalars()
        .all()
    )
    lats = [r.latency_ms for r in rows if r.state == "up" and r.latency_ms is not None]
    return {
        "monitor_id": monitor_id,
        "range": range_,
        "points": [
            {
                "checked_at": r.created_at.isoformat() + "Z",
                "state": r.state,
                "latency_ms": r.latency_ms,
            }
            for r in rows
        ],
        "avg_ms": round(sum(lats) / len(lats)) if lats else None,
        "max_ms": max(lats) if lats else None,
        "up_pct": round(len(lats) / len(rows) * 100, 1) if rows else None,
    }


async def cleanup_port_samples(session: AsyncSession) -> int:
    from datetime import timedelta

    from sqlalchemy import delete as _delete

    from app.models.port import PortProbeSample

    cutoff = datetime.utcnow() - timedelta(days=SAMPLE_RETENTION_DAYS)
    result = await session.execute(
        _delete(PortProbeSample).where(PortProbeSample.created_at < cutoff)
    )
    await session.commit()
    return result.rowcount or 0
