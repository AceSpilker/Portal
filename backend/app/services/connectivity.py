"""连通性探测服务（M04-13；dev-plan P3.6）：应用×入口的通断/延迟矩阵。

探测方式：TCP 连接（对 http/https/ssh/lan/vpn/custom 通用），
延迟取连接耗时；无法解析出 host:port 的入口标记 unknown。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy import select

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


# ---- 入口延迟历史（M04-14；dev-plan P15.4）----

RETENTION_DAYS = 7  # 采样保留天数（趋势定位足够，防库膨胀）


async def record_url_samples(session, results: list[dict], app_id_by_url: dict[int, int]) -> None:
    """把入口探测结果写入 url_probe_samples（预检/矩阵/定时轮询共用）。"""
    from datetime import datetime

    from app.models.probe import UrlProbeSample

    for r in results:
        url_id = r.get("id")
        if url_id is None:
            continue
        session.add(
            UrlProbeSample(
                url_id=url_id,
                app_id=app_id_by_url.get(url_id, 0),
                state=r.get("state", "unknown"),
                latency_ms=r.get("latency_ms"),
                checked_at=datetime.utcnow(),
            )
        )
    await session.commit()


async def probe_all_urls(session) -> int:
    """定时任务（P15.4）：探测全部启用应用的所有入口并记录采样。返回采样条数。"""
    from sqlalchemy.orm import selectinload

    from app.models.portal import App

    apps = (
        (
            await session.execute(
                select(App)
                .where(App.deleted.is_(False), App.enabled.is_(True))
                .options(selectinload(App.urls))
            )
        )
        .scalars()
        .all()
    )
    matrix = await probe_apps(apps)
    results: list[dict] = []
    app_id_by_url: dict[int, int] = {}
    for row in matrix["apps"]:
        for u in row["urls"]:
            results.append(u)
            app_id_by_url[u["id"]] = row["id"]
    await record_url_samples(session, results, app_id_by_url)
    return len(results)


async def cleanup_url_samples(session) -> int:
    """清理过期入口延迟采样（保留 RETENTION_DAYS 天）。"""
    from datetime import datetime, timedelta

    from sqlalchemy import delete

    from app.models.probe import UrlProbeSample

    cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
    result = await session.execute(delete(UrlProbeSample).where(UrlProbeSample.checked_at < cutoff))
    await session.commit()
    return result.rowcount or 0
