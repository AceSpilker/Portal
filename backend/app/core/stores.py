"""统一键值存储抽象（M15-14；dev-plan P25.1/P25.3/P25.4）。

- MemoryStore：进程内存实现（未配置 Redis 时自动降级，行为与 Redis 版一致）；
- RedisStore：redis.asyncio 封装（key 前缀隔离）；
- StoreManager（单例 stores）：当前模式 redis/memory，操作失败自动降级内存，
  恢复后由健康检查回切（回切不迁移内存数据——Redis 是事实源，内存仅兜底）。

用途（P25.2/P25.3）：登出黑名单、登录限速计数、传输加密会话密钥、
监控实时概览缓存等热点键值。
"""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger("portal.stores")


class MemoryStore:
    """进程内存实现：TTL 用到期时间戳惰性清理。"""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float | None]] = {}  # key -> (value, expires_at)

    def _alive(self, key: str) -> bool:
        item = self._data.get(key)
        if item is None:
            return False
        _, exp = item
        if exp is not None and exp <= time.time():
            self._data.pop(key, None)
            return False
        return True

    async def get(self, key: str) -> str | None:
        if not self._alive(key):
            return None
        return self._data[key][0]

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        self._data[key] = (value, (time.time() + ttl) if ttl else None)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def exists(self, key: str) -> bool:
        return self._alive(key)

    def clear(self) -> None:
        """测试辅助：清空全部键。"""
        self._data.clear()


class RedisStore:
    """redis.asyncio 封装；所有键带前缀（多实例隔离）。"""

    def __init__(self, client: Any, prefix: str) -> None:
        self._client = client
        self.prefix = prefix

    def k(self, key: str) -> str:
        return f"{self.prefix}{key}"

    async def get(self, key: str) -> str | None:
        v = await self._client.get(self.k(key))
        return v.decode() if isinstance(v, bytes) else v

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        if ttl:
            await self._client.set(self.k(key), value, ex=ttl)
        else:
            await self._client.set(self.k(key), value)

    async def delete(self, key: str) -> None:
        await self._client.delete(self.k(key))

    async def exists(self, key: str) -> bool:
        return bool(await self._client.exists(self.k(key)))

    async def ping(self) -> bool:
        return bool(await self._client.ping())


class StoreManager:
    """模式管理：redis/memory；操作异常自动降级，恢复检查后回切。"""

    def __init__(self) -> None:
        self.mode = "memory"  # memory / redis / redis-degraded
        self._memory = MemoryStore()
        self._redis: RedisStore | None = None
        self.enabled = False
        self.last_error = ""
        self.key_prefix = "portal:"

    @property
    def store(self) -> MemoryStore | RedisStore:
        """当前事实存储：降级态回落内存。"""
        if self.mode == "redis" and self._redis is not None:
            return self._redis
        return self._memory

    @property
    def degraded(self) -> bool:
        return self.mode == "redis-degraded"

    def configure_memory(self) -> None:
        """未启用 Redis：纯内存模式。"""
        self.mode = "memory"
        self.enabled = False
        self._redis = None

    async def configure_redis(
        self, host: str, port: int, password: str, db: int, prefix: str
    ) -> bool:
        """启用 Redis：建连接并 PING 验证；失败保持内存并记录错误。"""
        import redis.asyncio as aioredis

        self.enabled = True
        self.key_prefix = prefix or "portal:"
        client = aioredis.Redis(
            host=host, port=port, password=password or None, db=db,
            socket_timeout=2.0, socket_connect_timeout=2.0,
            decode_responses=False,
        )
        try:
            await client.ping()
        except Exception as exc:
            self.last_error = str(exc)[:300]
            self.mode = "memory"
            self._redis = None
            try:
                await client.aclose()
            except Exception:
                pass
            return False
        self._redis = RedisStore(client, self.key_prefix)
        self.mode = "redis"
        self.last_error = ""
        return True

    async def ping(self) -> bool:
        """健康检查（P25.4）：redis 模式验证连通；降级态探测回切。"""
        if not self.enabled or self._redis is None:
            return False
        try:
            ok = await self._redis.ping()
        except Exception as exc:
            ok = False
            self.last_error = str(exc)[:300]
        if ok:
            if self.mode != "redis":
                log.info("redis recovered, switching back from %s", self.mode)
            self.mode = "redis"
            self.last_error = ""
        else:
            if self.mode == "redis":
                log.warning("redis unreachable, degrading to memory")
            self.mode = "redis-degraded"
        return ok

    def view(self) -> dict:
        """健康自检/状态端点输出。"""
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "connected": self.mode == "redis",
            "degraded": self.degraded,
            "key_prefix": self.key_prefix,
            "last_error": self.last_error,
        }


stores = StoreManager()
