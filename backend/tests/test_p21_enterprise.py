# ruff: noqa: E501
"""P21 测试关卡：监控与企业化进阶（M17/M08；dev-plan 21.1~21.4）。

- CSV 导出与性能报表（形状/聚合）；
- Agent：注册→上报（token 鉴权）→清单；错 token 401；未注册 token 403；
- SNMP：BER 编解码 round-trip（自构造报文）；
- Docker 增强：批量操作/Mirror 镜像列表/更新检测（MockTransport）；
- WebSSH：开关关闭时 WS 拒绝。
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password

ADMIN = "admin"
ADMIN_PASS = "portal-p21"

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


def test_01_monitor_export_and_report(client: TestClient):
    """CSV 导出（21.1）+ 性能报表聚合形状。"""
    h = _admin(client)
    # 种子一条样本（空库 CSV 为空）
    import asyncio
    from datetime import datetime as _dt

    # 直接用应用会话插入
    from app.db.session import SessionLocal
    from app.models.monitor import MonitorSample

    async def _seed():
        async with SessionLocal() as session:
            session.add(
                MonitorSample(ts=_dt.utcnow(), cpu=12.5, mem='{"total": 8000, "used": 4000}',
                              disks="[]", nets="[]", io="[]", temps="[]", procs="[]")
            )
            await session.commit()

    asyncio.run(_seed())
    exp = client.get("/api/monitor/export?metric=cpu&range=24h", headers=h).json()["data"]
    assert exp["filename"].endswith(".csv") and "ts" in exp["csv"].splitlines()[0]
    rep = client.get("/api/monitor/report?days=7", headers=h).json()["data"]
    assert "days" in rep and isinstance(rep["days"], list)
    # 非法 metric 422
    assert client.get("/api/monitor/export?metric=bad", headers=h).status_code == 422


def test_02_agent_lifecycle(client: TestClient):
    """Agent（21.3）：注册生成 token→上报→清单在线；错 token 401；未注册 token 403。"""
    h = _admin(client)
    # 上报未启用（无 token 配置）403
    r0 = client.post("/api/monitor/agents/report", json={
        "token": "x", "hostname": "node-a", "cpu_pct": 1, "mem_pct": 2, "disk_pct": 3,
    })
    assert r0.status_code == 403
    # 注册
    reg = client.post("/api/monitor/agents", json={"hostname": "node-a"}, headers=h)
    assert reg.status_code == 200
    token = reg.json()["data"]["token"]
    assert token
    # 上报
    rep = client.post("/api/monitor/agents/report", json={
        "token": token, "hostname": "node-a", "cpu_pct": 11.5, "mem_pct": 44.0,
        "disk_pct": 66.0, "uptime_s": 7200, "version": "test",
    })
    assert rep.status_code == 200
    # 错 token 401
    bad = client.post("/api/monitor/agents/report", json={
        "token": "wrong", "hostname": "node-a", "cpu_pct": 1, "mem_pct": 1, "disk_pct": 1,
    })
    assert bad.status_code == 401
    # 清单
    agents = client.get("/api/monitor/agents", headers=h).json()["data"]
    node = next(a for a in agents if a["hostname"] == "node-a")
    assert node["cpu_pct"] == 11.5 and node["online"] is True
    # 脚本生成
    script = client.get("/api/monitor/agents/script", headers=h).json()["data"]
    assert "psutil" in script["script"] and script["token"]


def test_03_snmp_codec():
    """SNMP（21.3）：BER 编解码 round-trip（构造 GET→解析 OID/NULL 值）。"""
    from app.services.snmp import build_get, parse_response

    pkt = build_get("1.3.6.1.2.1.1.3.0", "public", request_id=7)
    assert pkt.startswith(b"\x30") and b"public" in pkt
    err, oid, value = parse_response(pkt)
    assert err == 0 and oid == "1.3.6.1.2.1.1.3.0" and value is None


def test_04_docker_enhanced(client: TestClient, monkeypatch):
    """Docker 增强（21.4）：批量操作/镜像列表/更新检测（MockTransport）。"""
    h = _admin(client)
    from app.services import docker_svc

    captured = []

    def handler(request: "object") -> "object":
        import httpx as _httpx

        url = request.url.path
        if url.endswith("/containers/json"):
            return _httpx.Response(200, json=[
                {"Id": "abc123", "Names": ["/web"], "Image": "nginx:latest",
                 "State": "running", "Created": 1000000000},
            ])
        if url.endswith("/images/json"):
            return _httpx.Response(200, json=[
                {"Id": "sha256:img1", "RepoTags": ["nginx:latest"], "Created": 1000000000,
                 "Size": 100},
            ])
        if "/containers/web/" in url:
            captured.append(url.rsplit("/", 1)[-1])
            return _httpx.Response(200, text="")
        if url.startswith("/images/"):
            return _httpx.Response(200, text="")
        return _httpx.Response(404)

    import httpx as _httpx

    monkeypatch.setattr(docker_svc, "enabled", lambda: True)

    class FakeCM:
        """模拟 _client()：返回支持 async with 的假客户端。"""

        async def __aenter__(self):
            return _httpx.AsyncClient(
                base_url="http://docker", transport=_httpx.MockTransport(handler)
            )

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(docker_svc, "_client", lambda: FakeCM())

    batch = client.post("/api/docker/batch", json={"names": ["web", "ghost"], "op": "restart"}, headers=h)
    data = batch.json()["data"]
    assert data["ok_count"] >= 1 and any(r["name"] == "ghost" for r in data["results"])
    images = client.get("/api/docker/images", headers=h).json()["data"]
    assert images[0]["tags"] == ["nginx:latest"]
    updates = client.get("/api/docker/updates", headers=h).json()["data"]
    assert updates and updates[0]["tag"] == "nginx:latest" and updates[0]["created_days_old"] >= 30
    # 镜像删除
    assert client.delete("/api/docker/images/sha256:img1", headers=h).status_code == 200


def test_05_webssh_disabled(client: TestClient):
    """WebSSH（21.2）：开关关闭时 WS 直接拒绝（4403/4401）。"""

    from app.core.security import create_access_token

    token = create_access_token(1, 0)
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/ssh-terminal?token={token}&cred=1") as ws:
            ws.receive_text()


def test_10_health_report_nodes_fields(client: TestClient):
    """健康自检仍可用（回归）。"""
    h = _admin(client)
    r = client.get("/api/system/health-report/full", headers=h).json()["data"]
    assert "mysql" in r and "redis" in r
