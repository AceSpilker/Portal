"""P6 测试关卡：应用探活（三种探测判定 / 状态翻转去抖 / 通知 / 端点权限）。

HTTP 探测经 httpx.MockTransport 注入（确定性）；TCP 用本地 socket 监听。
状态翻转/通知走独立内存库（隔离 TestClient lifespan 的调度任务）。
"""

import asyncio
import socket
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import hash_password
from app.models import Base
from app.services.probe import _probe_http, _probe_tcp, probe_once

ADMIN_USER = "admin"
ADMIN_PASS = "portal-p2"

_tokens: dict = {}


def _reset_db_state() -> None:
    db_file = Path(settings.data_dir) / "portal.db"
    conn = sqlite3.connect(db_file)
    try:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (ADMIN_USER,)).fetchone():
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE username = ?",
                (hash_password(ADMIN_PASS), ADMIN_USER),
            )
        else:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, is_active, prefs, token_version)"
                " VALUES (?, ?, 'admin', 1, '{}', 0)",
                (ADMIN_USER, hash_password(ADMIN_PASS)),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="module", autouse=True)
def _setup(client: TestClient):
    _reset_db_state()
    _tokens.clear()


def _admin(client: TestClient) -> dict:
    if "admin" not in _tokens:
        resp = client.post("/api/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
        assert resp.status_code == 200, resp.text
        _tokens["admin"] = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {_tokens['admin']}"}


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _mock_http(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


# ============ 三种探测判定（M07-1；P6.1）============


@pytest.mark.anyio
async def test_01_http_probe_states():
    """http：2xx/3xx up，4xx/5xx down；关键字命中判定。"""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/ok":
            return httpx.Response(200, text="hello Portal")
        if path == "/notfound":
            return httpx.Response(404, text="nope")
        if path == "/keyword":
            return httpx.Response(200, text="welcome to Jellyfin")
        if path == "/fail":
            raise httpx.ConnectError("connection refused")
        return httpx.Response(500)

    transport = _mock_http(handler)
    base = "http://probe.test"
    assert (await _probe_http(f"{base}/ok", None, transport))[0] == "up"
    state, latency, msg = await _probe_http(f"{base}/notfound", None, transport)
    assert state == "down" and msg == "HTTP 404"
    state, _, msg = await _probe_http(f"{base}/keyword", "Jellyfin", transport)
    assert state == "up"
    state, _, msg = await _probe_http(f"{base}/keyword", "qBittorrent", transport)
    assert state == "down" and msg == "关键字未命中"
    # 连接失败：latency 不可得
    state, latency, _ = await _probe_http(f"{base}/fail", None, transport)
    assert state == "down" and latency is None


@pytest.mark.anyio
async def test_02_tcp_probe():
    """tcp：本地监听端口 up；未监听端口 down；坏格式报错。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        state, latency, _ = await _probe_tcp(f"127.0.0.1:{port}")
        assert state == "up" and latency is not None
    finally:
        s.close()
    dead = _free_port()
    state, msg = (await _probe_tcp(f"127.0.0.1:{dead}"))[0:2]
    assert state == "down"
    state, _, msg = await _probe_tcp("127.0.0.1:notaport")
    assert state == "down" and "host:port" in msg


@pytest.mark.anyio
async def test_03_keyword_target_format():
    """keyword 目标 `url::关键字` 解析。"""
    transport = _mock_transport_keyword()
    state, _, msg = await probe_once(
        _app("keyword", "http://kw.test/::Release"),
        transport=transport,
    )
    assert state == "up" and "命中" not in msg


def _mock_transport_keyword() -> httpx.MockTransport:
    return httpx.MockTransport(
        lambda request: httpx.Response(200, text="new Release published")
    )


def _app(htype: str, target: str, app_id: int = 1):
    from app.models.portal import App

    return App(
        id=app_id, name="探活测试", health_type=htype, health_target=target,
        health_interval=10, enabled=1, deleted=0,
    )


# ============ 状态翻转去抖与通知（M07-2/5；P6.2/P6.4）============


def test_04_flip_debounce_and_notification():
    """状态翻转才记事件/通知；相同状态重复探测不产生新事件。"""

    async def _run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with maker() as s:
            from app.models.probe import AppStatus, Notification, ProbeEvent
            from app.services.probe import apply_result

            app = _app("tcp", "127.0.0.1:80", app_id=99)
            s.add(app)
            await s.commit()
            ev1 = await apply_result(s, app, "down", None, "端口连接失败")
            ev2 = await apply_result(s, app, "down", None, "端口连接失败")  # 未翻转
            ev3 = await apply_result(s, app, "up", 12, "")
            events = len((await s.execute(ProbeEvent.__table__.select())).fetchall())
            notes = (await s.execute(Notification.__table__.select())).fetchall()
            status = await s.get(AppStatus, 99)
        await engine.dispose()
        return ev1, ev2, ev3, events, notes, status


    ev1, ev2, ev3, events, notes, status = asyncio.run(_run())
    assert ev1 is not None and ev2 is None and ev3 is not None  # 未翻转不广播
    assert events == 2  # down + up 两条事件
    assert {n.title for n in notes} == {"探活测试 已下线", "探活测试 已恢复"}
    assert status.state == "up" and status.latency_ms == 12


# ============ 端点契约（P6.3）============


def test_05_check_endpoint_and_permission(client: TestClient):
    """check 端点：未登录 401；立即探活返回状态；status 接口含该应用。"""
    assert client.post("/api/apps/1/check").status_code == 401

    resp = client.post("/api/apps", json={"name": "探活目标应用"}, headers=_admin(client))
    app_id = resp.json()["data"]["id"]
    client.put(
        f"/api/apps/{app_id}",
        json={"health_type": "tcp", "health_target": f"127.0.0.1:{_free_port()}"},
        headers=_admin(client),
    )
    resp = client.post(f"/api/apps/{app_id}/check", headers=_admin(client))
    assert resp.status_code == 200
    assert resp.json()["data"]["state"] in ("up", "down")  # 目标未监听 → down 合法

    resp = client.get("/api/probe/status", headers=_admin(client))
    assert resp.status_code == 200
    assert str(app_id) in resp.json()["data"]

    resp = client.get("/api/notifications", headers=_admin(client))
    assert resp.status_code == 200
    # P9 起 /notifications 为分页对象 {items, total, unread}（api-spec §4.9）
    data = resp.json()["data"]
    assert isinstance(data["items"], list) and data["unread"] >= 1
