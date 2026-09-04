"""登录失败限速（M01-6）：同 IP 60 秒内失败 5 次即临时锁定。

P25.2：计数从进程内存迁入统一存储（stores）——Redis 模式下重启/多进程
共享；未配置 Redis 时降级为 MemoryStore，行为不变。
"""

from __future__ import annotations

import json
import time

from app.core.stores import stores

_WINDOW = 60.0
_MAX_FAILS = 5
_PREFIX = "rl:"


def _prune(hits: list[float], now: float) -> list[float]:
    return [t for t in hits if now - t < _WINDOW]


async def _load(ip: str) -> list[float]:
    raw = await stores.store.get(_PREFIX + ip)
    if not raw:
        return []
    try:
        return [float(t) for t in json.loads(raw)]
    except (ValueError, TypeError):
        return []


async def is_locked(ip: str) -> bool:
    hits = _prune(await _load(ip), time.time())
    return len(hits) >= _MAX_FAILS


async def record_fail(ip: str) -> None:
    hits = _prune(await _load(ip), time.time())
    hits.append(time.time())
    await stores.store.set(_PREFIX + ip, json.dumps(hits), ttl=int(_WINDOW))


async def record_success(ip: str) -> None:
    await stores.store.delete(_PREFIX + ip)


async def reset(ip: str) -> None:
    """测试辅助：清除指定 IP 的失败记录。"""
    await stores.store.delete(_PREFIX + ip)
