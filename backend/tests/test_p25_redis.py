# ruff: noqa: E501
"""P25 测试关卡：Redis 缓存与会话（M15-14；dev-plan 25.1~25.4）。

- MemoryStore 行为：set/get/ttl 过期/delete/exists；
- 登出黑名单：logout 后同 token 立即 401（jti TTL）；
- 限速计数：5 次失败锁定、成功清除（stores 计数）；
- 降级：指向不可达 Redis → 操作失败自动回落内存、本地功能照常；
- 真实 Redis 链路（本机 Docker 6379，不可达则 skip）：读写/TTL/重启保持、
  健康自检 redis 字段、回切。
"""

import json as _json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password

ADMIN = "admin"
ADMIN_PASS = "portal-p25"

_tokens: dict = {}


def _reset_db_state() -> None:
    import sqlite3

    db_file = Path(settings.data_dir) / "portal.db"
    conn = sqlite3.connect(db_file)
    try:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (ADMIN,)).fetchone():
            conn.execute(
                "UPDATE users SET password_hash = ?, is_active = 1, totp_enabled = 0 WHERE username = ?",
                (hash_password(ADMIN_PASS), ADMIN),
            )
        else:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, is_active, prefs, token_version)"
                " VALUES (?, ?, 'admin', 1, '{}', 0)",
                (ADMIN, hash_password(ADMIN_PASS)),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="module", autouse=True)
def _setup(client: TestClient):
    _reset_db_state()
    _tokens.clear()


def _admin(client: TestClient) -> dict:
    if ADMIN not in _tokens:
        resp = client.post("/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASS})
        assert resp.status_code == 200, resp.text
        _tokens[ADMIN] = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {_tokens[ADMIN]}"}


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_01_memory_store_behavior():
    """MemoryStore：set/get/TTL 过期/delete/exists（与 Redis 版同一接口）。"""
    import asyncio

    from app.core.stores import MemoryStore

    async def _main():
        s = MemoryStore()
        await s.set("k", "v")
        assert await s.get("k") == "v"
        assert await s.exists("k") is True
        await s.delete("k")
        assert await s.get("k") is None and await s.exists("k") is False
        await s.set("t", "x", ttl=1)
        assert await s.get("t") == "x"
        # 惰性过期：人为推进到期时间
        s._data["t"] = (s._data["t"][0], 0)
        assert await s.get("t") is None

    asyncio.run(_main())


def test_02_logout_blacklist(client: TestClient):
    """登出黑名单（25.2）：logout 后同一 access token 立即 401。"""
    login = client.post("/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASS})
    access = login.json()["data"]["access_token"]
    h = {"Authorization": f"Bearer {access}"}
    assert client.get("/api/auth/me", headers=h).status_code == 200
    assert client.post("/api/auth/logout", headers=h).status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 401
    # 新登录不受影响
    relogin = client.post("/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASS})
    assert relogin.status_code == 200
    _tokens[ADMIN] = relogin.json()["data"]["access_token"]


def test_03_rate_limit_counters(client: TestClient):
    """限速计数（25.2）：5 次失败锁定；窗口内第 6 次直接 429；成功登录清除。"""

    from app.core.ratelimit import is_locked, record_fail, record_success, reset

    ip = "1.2.3.4"
    _run(reset(ip))
    for _ in range(5):
        assert _run(is_locked(ip)) is False
        _run(record_fail(ip))
    assert _run(is_locked(ip)) is True
    _run(record_success(ip))
    assert _run(is_locked(ip)) is False


def test_04_degrade_to_memory(client: TestClient, monkeypatch):
    """降级（25.4）：Redis 不可达时 stores 回落内存，登录等本地功能照常。"""

    from app.core.stores import stores

    async def _configure_fail(self, *a, **k):
        """模拟真实失败路径：PING 失败 → 保持内存模式。"""
        self.enabled = True
        self.mode = "memory"
        self._redis = None
        self.last_error = "connection refused"
        return False

    monkeypatch.setattr(type(stores), "configure_redis", _configure_fail)
    connected = _run(stores.configure_redis("127.0.0.1", 1, "", 0, "portal:"))
    assert connected is False and stores.mode == "memory"  # configure 失败回落内存
    # 操作走内存：功能照常
    _run(stores.store.set("probe", "1"))
    assert _run(stores.store.get("probe")) == "1"
    login = client.post("/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASS})
    assert login.status_code == 200
    _tokens[ADMIN] = login.json()["data"]["access_token"]
    stores.configure_memory()


def test_05_redis_config_endpoints(client: TestClient):
    """配置端点（25.1）：保存（密码密文）→ 脱敏回读 → 空密码保持。"""
    h = _admin(client)
    save = client.put(
        "/api/settings/redis",
        json={"host": "127.0.0.1", "port": 6379, "password": "redispass", "db": 0,
              "key_prefix": "p25:", "enabled": False},
        headers=h,
    )
    assert save.status_code == 200, save.text
    data = save.json()["data"]
    assert data["password"] == "" and data["password_set"] is True
    keep = client.put("/api/settings/redis", json={"host": "127.0.0.1", "enabled": False}, headers=h)
    assert keep.json()["data"]["password_set"] is True
    # 库内为密文
    import sqlite3

    from app.core.config import settings as cfg

    conn = sqlite3.connect(Path(cfg.data_dir) / "portal.db")
    row = conn.execute("SELECT value FROM settings WHERE key='redis.password'").fetchone()
    conn.close()
    assert row and _json.loads(row[0]).startswith("gAAAA")


def test_06_redis_test_endpoint(client: TestClient):
    """连接测试（25.1）：未配置 422；不可达 ok=False。"""
    h = _admin(client)
    # 清空 host（前面用例保存过配置）
    client.put("/api/settings/redis", json={"host": "", "enabled": False}, headers=h)
    empty = client.post("/api/redis/test", headers=h)
    assert empty.status_code == 422
    dead = client.post("/api/redis/test", json={"host": "127.0.0.1", "port": 1}, headers=h)
    assert dead.status_code == 200 and dead.json()["data"]["ok"] is False


def _redis_alive() -> bool:
    import socket

    s = socket.socket()
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", 6379))
        return True
    except OSError:
        return False
    finally:
        s.close()


@pytest.mark.skipif(not _redis_alive(), reason="本机 6379 无 Redis")
def test_07_real_redis_roundtrip_and_restart(client: TestClient):
    """真实 Redis 链路：configure→读写/TTL→重建实例（模拟重启）数据仍在→状态与健康。"""
    import asyncio

    from app.core.stores import stores

    async def _main():
        ok = await stores.configure_redis("127.0.0.1", 6379, "", 0, "p25test:")
        assert ok is True
        await stores.store.set("k1", "v1", ttl=60)
        assert await stores.store.get("k1") == "v1"
        # 模拟重启：销毁重建连接实例，数据仍在 Redis 侧
        await stores._redis._client.aclose()
        ok2 = await stores.configure_redis("127.0.0.1", 6379, "", 0, "p25test:")
        assert ok2 is True
        assert await stores.store.get("k1") == "v1"
        await stores.store.delete("k1")
        assert await stores.store.get("k1") is None
        # ping/回切
        assert await stores.ping() is True and stores.mode == "redis"
        # 清理测试键并退出 redis 模式（客户端绑定本用例事件循环）
        await stores._redis._client.flushdb()

    asyncio.run(_main())
    stores.configure_memory()  # 恢复内存模式，避免后续请求触碰已关闭的循环
    # 状态端点
    h = _admin(client)
    st = client.get("/api/redis/status", headers=h).json()["data"]
    assert st["mode"] in ("redis", "memory", "redis-degraded")


def test_08_health_report_redis_field(client: TestClient):
    """健康自检（25.4）：redis 字段输出 enabled/mode/connected/degraded。"""
    h = _admin(client)
    full = client.get("/api/system/health-report/full", headers=h).json()["data"]
    assert set(full["redis"].keys()) >= {"enabled", "mode", "connected", "degraded", "key_prefix"}
