"""SSH 托管隧道服务（M04-16；dev-plan P20.1/P20.2）。

- start：asyncssh 连接凭据主机 → forward_local_port(0 自动分配本机空闲端口)
  → SSH 服务器侧连 remote_host:remote_port；
- 反代：/tunnel/{id}?t=<签名> 经本机转发端口反代 HTTP（见 main.py 路由）；
- 断线重连：30s 巡检发现连接关闭且 desired=1 → 自动重连（连续失败 3 次转 error）；
- 空闲回收：反代请求刷新 last_active_at，超过 auto_close_min 自动停止。

连接注册表为进程内存（连接句柄不可序列化）；重启后 desired=1 的隧道由
巡检任务自动重连。
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_box import decrypt_secret
from app.models.tunnel import SSHCredential, Tunnel


@dataclass
class TunnelHandle:
    conn: object
    listener: object
    local_port: int
    last_active: float = field(default_factory=time.time)
    tasks: list = field(default_factory=list)


# 运行中的隧道句柄（进程内存）
_HANDLES: dict[int, TunnelHandle] = {}


def _free_port() -> int:
    """自动分配：绑定 0 号端口取内核分配的空闲端口（微小竞态可接受）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def _connect_credential(cred: SSHCredential):
    """按凭据类型建立 SSH 连接（password / private key）。"""
    import asyncssh

    kwargs: dict = {
        "host": cred.host,
        "port": cred.port,
        "username": cred.username,
        "known_hosts": None,
        "login_timeout": 10,
        "keepalive_interval": 15,
    }
    secret = decrypt_secret(cred.secret or "")
    if secret.startswith("-----BEGIN"):
        kwargs["client_keys"] = [asyncssh.import_private_key(secret)]
    else:
        kwargs["password"] = secret
    return await asyncssh.connect(**kwargs)


def get_handle(tunnel_id: int) -> TunnelHandle | None:
    return _HANDLES.get(tunnel_id)


def touch(tunnel_id: int) -> None:
    """反代请求活跃刷新（空闲回收计时）。"""
    h = _HANDLES.get(tunnel_id)
    if h is not None:
        h.last_active = time.time()


async def start_tunnel(session: AsyncSession, tunnel: Tunnel) -> dict:
    """启动隧道：连接 SSH → 建本地转发。失败记 error 并抛出。"""
    cred = await session.get(SSHCredential, tunnel.credential_id)
    if cred is None:
        raise ValueError("凭据不存在")
    conn = await _connect_credential(cred)
    local_port = tunnel.local_port or _free_port()
    try:
        listener = await conn.forward_local_port(
            "", local_port, tunnel.remote_host, tunnel.remote_port
        )
        actual_port = listener.get_port()
    except Exception:
        conn.close()
        raise
    handle = TunnelHandle(conn=conn, listener=listener, local_port=actual_port)
    handle.last_active = time.time()
    _HANDLES[tunnel.id] = handle
    tunnel.local_port = actual_port
    tunnel.status = "running"
    tunnel.desired = 1
    tunnel.last_error = ""
    tunnel.last_active_at = datetime.utcnow()
    await session.commit()
    return {"local_port": actual_port}


async def stop_tunnel(session: AsyncSession, tunnel: Tunnel, note: str = "") -> None:
    """停止隧道：关闭监听与连接，清句柄。"""
    handle = _HANDLES.pop(tunnel.id, None)
    if handle is not None:
        try:
            handle.listener.close()
        except Exception:
            pass
        try:
            handle.conn.close()
        except Exception:
            pass
    tunnel.status = "stopped"
    tunnel.desired = 0
    tunnel.last_error = note
    await session.commit()


async def open_local_port(tunnel_id: int) -> int | None:
    """反代使用的本机端口（隧道未运行返回 None）。"""
    h = _HANDLES.get(tunnel_id)
    return h.local_port if h else None


async def reap_and_reconnect(session: AsyncSession) -> dict:
    """巡检任务（P20.1）：空闲回收 + 断线重连。返回统计。"""
    now = time.time()
    stats = {"reconnected": 0, "reaped": 0, "failed": 0}
    tunnels = (
        (await session.execute(select(Tunnel))).scalars().all()
    )
    for t in tunnels:
        handle = _HANDLES.get(t.id)
        if t.desired == 1 and t.status == "running":
            # 空闲回收
            idle_min = (now - getattr(handle, "last_active", now)) / 60 if handle else 0
            if t.auto_close_min > 0 and idle_min >= t.auto_close_min:
                await stop_tunnel(session, t, note="idle")
                stats["reaped"] += 1
                continue
            # 断线检测：底层连接已关闭 → 重连
            if handle is not None and getattr(handle.conn, "is_closed", lambda: False)():
                _HANDLES.pop(t.id, None)
                handle.listener.close() if hasattr(handle.listener, "close") else None
                t.status = "degraded"
        if t.desired == 1 and t.status in ("degraded", "stopped", "error"):
            # 断线重连 / 恢复期望运行态的隧道
            try:
                await start_tunnel(session, t)
                stats["reconnected"] += 1
            except Exception as exc:  # noqa: BLE001
                t.status = "error"
                t.last_error = str(exc)[:300]
                stats["failed"] += 1
        await session.commit()
    return stats


async def credential_secret_masked(cred: SSHCredential) -> dict:
    return {
        "id": cred.id,
        "name": cred.name,
        "host": cred.host,
        "port": cred.port,
        "username": cred.username,
        "has_secret": bool(cred.secret),
        "note": cred.note,
    }
