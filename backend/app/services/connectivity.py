"""连通性探测服务（M04-13；dev-plan P3.6）：应用×入口的通断/延迟矩阵。

探测方式：TCP 连接（对 http/https/ssh/lan/vpn/custom 通用），
延迟取连接耗时；无法解析出 host:port 的入口标记 unknown。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

PROBE_TIMEOUT = 2.0  # 单入口超时（秒）
_CONCURRENCY = 16  # 并发探测上限

_DEFAULT_PORT = {"http": 80, "https": 443, "ssh": 22}


def parse_host_port(url: str) -> tuple[str, int] | None:
    """从入口地址提取 (host, port)；无法解析返回 None。

    兼容：完整 URL（https://host:port/…）、裸 authority（host:port、user@host:22）、
    ssh 入口常用写法（user@jump:22）。IPv6 需写成方括号形式。
    """
    text = (url or "").strip()
    if not text:
        return None
    if "://" not in text:
        text = "//" + text
    try:
        parts = urlsplit(text)
        host = parts.hostname
        if not host:
            return None
        if parts.port is not None:
            port = parts.port
        else:
            scheme = parts.scheme.lower()
            port = _DEFAULT_PORT.get(scheme, 80)
    except ValueError:  # 非法端口等（如 host:99999）
        return None
    return host, port


async def probe_tcp(host: str, port: int, timeout: float = PROBE_TIMEOUT) -> tuple[str, int | None]:
    """TCP 探测：返回 (state, latency_ms)；state ∈ up/down。"""
    start = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, TimeoutError):
        return "down", None
    latency = int((time.perf_counter() - start) * 1000)
    writer.close()
    try:
        await writer.wait_closed()
    except (OSError, TimeoutError):
        pass
    return "up", latency


async def _probe_url(u) -> dict:
    parsed = parse_host_port(u.url)
    if parsed is None:
        return {"id": u.id, "access_type": u.access_type, "url": u.url, "label": u.label,
                "state": "unknown", "latency_ms": None}
    state, latency = await probe_tcp(*parsed)
    return {"id": u.id, "access_type": u.access_type, "url": u.url, "label": u.label,
            "state": state, "latency_ms": latency}


async def probe_apps(apps: list) -> dict:
    """并发探测应用全集，输出矩阵结构（api-spec §4.3）。"""
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _bounded(coro):
        async with sem:
            return await coro

    rows = []
    for app in apps:
        urls = list(app.urls)
        probed = await asyncio.gather(*(_bounded(_probe_url(u)) for u in urls)) if urls else []
        rows.append(
            {
                "id": app.id,
                "name": app.name,
                "urls": probed,
            }
        )
    return {
        "probed_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        "apps": rows,
    }
