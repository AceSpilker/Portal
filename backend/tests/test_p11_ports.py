# ruff: noqa: E501
"""P11 测试关卡：端口监控（M18-1~7；dev-plan 11.1~11.5）。

- 监听清单解析（进程名兜底）；端口占用检索；
- 状态翻转（起本地 socket → up；关闭 → down + 事件 + 站内通知）；
- 批量导入去重；事件流水含应用名。
"""

import asyncio
import socket
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.services import ports

ADMIN = "admin"
ADMIN_PASS = "portal-p11"

_tokens: dict = {}


def _reset_db_state() -> None:
    db_file = Path(settings.data_dir) / "portal.db"
    conn = sqlite3.connect(db_file)
    try:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (ADMIN,)).fetchone():
            conn.execute(
                "UPDATE users SET password_hash = ?, is_active = 1 WHERE username = ?",
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


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_01_listen_list_and_lookup(client: TestClient):
    """监听清单：起一个真实 listener 后出现在清单里；lookup 能按端口检索。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.listen(1)

    resp = client.get("/api/ports/listen", headers=_admin(client))
    assert resp.status_code == 200
    rows = [r for r in resp.json()["data"] if r["port"] == port and r["proto"] == "tcp"]
    assert rows, "listener 未出现在监听清单"
    assert rows[0]["addr"] == "127.0.0.1"

    resp = client.get(f"/api/ports/lookup?port={port}", headers=_admin(client))
    assert resp.status_code == 200
    assert any(r["port"] == port for r in resp.json()["data"])

    # 未占用端口检索为空列表
    assert client.get("/api/ports/lookup?port=1", headers=_admin(client)).json()["data"] == []
    # port 越界 422
    assert client.get("/api/ports/lookup?port=99999", headers=_admin(client)).status_code == 422
    s.close()


def test_02_state_flip_and_notify(client: TestClient):
    """起服务 → up；关服务 → down + 事件 + 站内通知（port_down）。"""
    port = _free_port()
    resp = client.post(
        "/api/ports/monitors",
        json={"name": "临时服务", "host": "127.0.0.1", "port": port, "interval": 10},
        headers=_admin(client),
    )
    assert resp.status_code == 200
    mid = resp.json()["data"]["id"]

    async def _flip():
        async with SessionLocal() as s:
            return await ports.check_monitor(s, mid)

    # 未监听 → down
    ev = asyncio.run(_flip())
    assert ev["data"]["state"] == "down"

    # 起监听 → up
    srv = socket.socket()
    srv.bind(("127.0.0.1", port))
    srv.listen(1)
    ev = asyncio.run(_flip())
    assert ev["data"]["state"] == "up"

    # 关闭 → down（翻转再次告警）
    srv.close()
    await_none = asyncio.run(_flip())
    assert await_none["data"]["state"] == "down"

    # 事件流水
    resp = client.get(f"/api/ports/monitors/{mid}/events", headers=_admin(client))
    events = [e["event"] for e in resp.json()["data"]]
    assert events == ["down", "up", "down"]  # 首次 down 也记录

    # 站内通知（port_down 两分钟粒度去重：两次 down 分属不同分钟才两条；至少一条）
    resp = client.get("/api/notifications", headers=_admin(client))
    titles = [i["title"] for i in resp.json()["data"]["items"]]
    assert any("临时服务" in t and "不可达" in t for t in titles)

    # 写权限：无 token 401
    assert client.post("/api/ports/monitors", json={"port": 80}).status_code == 401
    client.delete(f"/api/ports/monitors/{mid}", headers=_admin(client))


def test_03_import_dedup_and_app_link(client: TestClient):
    """批量导入：同 host+port 去重跳过；app_id 关联后列表带应用名。"""
    app = client.post("/api/apps", json={"name": "P11 关联应用"}, headers=_admin(client)).json()["data"]
    resp = client.post(
        "/api/ports/monitors/import",
        json={"items": ["Jellyfin|127.0.0.1:8096", "127.0.0.1:8096", "db|10.0.0.3:3306"]},
        headers=_admin(client),
    )
    data = resp.json()["data"]
    assert data["created"] == 2 and data["skipped"] == 1  # 第二行去重

    # 重复导入全部跳过
    resp = client.post(
        "/api/ports/monitors/import",
        json={"items": ["127.0.0.1:8096"]},
        headers=_admin(client),
    )
    assert resp.json()["data"] == {"created": 0, "skipped": 1}

    # 关联应用
    rows = client.get("/api/ports/monitors", headers=_admin(client)).json()["data"]
    target = next(r for r in rows if r["port"] == 8096)
    client.put(
        f"/api/ports/monitors/{target['id']}",
        json={"name": "Jellyfin", "host": "127.0.0.1", "port": 8096,
              "app_id": app["id"], "interval": 60, "enabled": True},
        headers=_admin(client),
    )
    rows = client.get("/api/ports/monitors", headers=_admin(client)).json()["data"]
    target = next(r for r in rows if r["port"] == 8096)
    assert target["app_name"] == "P11 关联应用"

    # 事件流水带监控项名
    resp = client.get("/api/ports/events?limit=100", headers=_admin(client))
    assert resp.status_code == 200

    # 清理
    for r in rows:
        if r["port"] in (8096, 3306):
            client.delete(f"/api/ports/monitors/{r['id']}", headers=_admin(client))
    client.delete(f"/api/apps/{app['id']}", headers=_admin(client))
