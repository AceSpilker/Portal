# ruff: noqa: E501
"""P12 测试关卡：Docker 容器管理基础（M08-1~4）。

- SDK 封装 mock（httpx.MockTransport 假 Docker Engine）；
- 敏感环境变量脱敏；
- 生命周期操作写审计；未启用时 503（退出标准：无 sock 系统零报错）。
"""

import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.services.docker_svc as svc
from app.core.config import settings
from app.core.security import hash_password

ADMIN = "admin"
ADMIN_PASS = "portal-p12"

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


def _fake_engine() -> httpx.MockTransport:
    """假 Docker Engine：两个容器 + stats/logs/inspect。"""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/containers/json":
            return httpx.Response(
                200,
                json=[
                    {"Id": "abc123", "Names": ["/web"], "Image": "nginx", "State": "running",
                     "Status": "Up 2 hours"},
                    {"Id": "def456", "Names": ["/db"], "Image": "postgres", "State": "exited",
                     "Status": "Exited (0) 1 min ago"},
                ],
            )
        if path.endswith("/stats") and "abc123" in path:
            base = 1_000_000_000
            return httpx.Response(
                200,
                json={
                    "cpu_stats": {"cpu_usage": {"total_usage": base + 50_000_000},
                                  "system_cpu_usage": base + 2_000_000_000, "online_cpus": 4},
                    "precpu_stats": {"cpu_usage": {"total_usage": base},
                                     "system_cpu_usage": base},
                    "memory_stats": {"usage": 104_857_600, "limit": 2_097_152_000},
                },
            )
        if path in ("/containers/abc123/logs", "/containers/web/logs"):
            return httpx.Response(200, text="\x01\x00\x00\x00\x00\x00\x00\x20hello docker log\nplain line")
        if path in ("/containers/abc123/json", "/containers/web/json"):
            return httpx.Response(
                200,
                json={
                    "Id": "abc123" * 5,
                    "Name": "/web",
                    "Config": {"Image": "nginx",
                               "Env": ["PATH=/usr/bin", "DB_PASSWORD=super-secret", "API_TOKEN=tok"]},
                    "State": {"Status": "running"},
                    "NetworkSettings": {"Ports": {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]}},
                    "Mounts": [{"Source": "/srv/web", "Destination": "/usr/share/nginx/html", "Mode": "rw"}],
                },
            )
        if path == "/containers/web/restart":
            return httpx.Response(204)
        if path in ("/containers/ghost/start", "/containers/ghost/restart"):
            return httpx.Response(404)
        return httpx.Response(404, json={"message": "not found"})

    return httpx.MockTransport(handler)


@pytest.fixture()
def _docker_on():
    svc.set_transport(_fake_engine())
    # 单测环境下绕过 enabled() 的真实 sock 依赖：临时视为启用
    real_enabled = svc.enabled
    svc.enabled = lambda: True
    yield
    svc.enabled = real_enabled
    svc.set_transport(None)


def test_01_disabled_returns_503(client: TestClient):
    """未启用（默认）→ 503，系统零报错（P12 退出标准）。"""
    resp = client.get("/api/docker/containers", headers=_admin(client))
    assert resp.status_code == 503
    assert client.get("/api/docker/status", headers=_admin(client)).json()["data"]["enabled"] is False


def test_02_list_and_detail_mask(client: TestClient, _docker_on):
    """列表运行中排前且带占用；详情环境变量脱敏。"""
    resp = client.get("/api/docker/containers", headers=_admin(client))
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert rows[0]["name"] == "web" and rows[0]["state"] == "running"
    assert rows[1]["state"] == "exited"
    web = rows[0]
    # cpu: (50M/2G)*4核*100 = 10%；mem: 100M/2000M = 5%
    assert web["cpu_percent"] == 10.0 and web["mem_percent"] == 5.0

    resp = client.get("/api/docker/containers/web/detail", headers=_admin(client))
    detail = resp.json()["data"]
    assert "DB_PASSWORD=******" in detail["env"]
    assert "API_TOKEN=******" in detail["env"]
    assert "PATH=/usr/bin" in detail["env"]
    assert detail["ports"][0]["host_port"] == "8080"
    assert detail["mounts"][0]["source"] == "/srv/web"


def test_03_logs_clean_mux(client: TestClient, _docker_on):
    """日志：多路复用帧头被清洗。"""
    resp = client.get("/api/docker/containers/web/logs?tail=50", headers=_admin(client))
    logs = resp.json()["data"]["logs"]
    assert "hello docker log" in logs and "plain line" in logs
    assert "\x01" not in logs


def test_04_operation_audit_and_404(client: TestClient, _docker_on):
    """restart 生效 + 写审计；404 容器返回 404。"""
    resp = client.post("/api/docker/containers/web/restart", headers=_admin(client))
    assert resp.status_code == 200 and resp.json()["data"]["ok"] is True

    db_file = Path(settings.data_dir) / "portal.db"
    conn = sqlite3.connect(db_file)
    try:
        rows = conn.execute(
            "SELECT action, detail FROM audit_logs WHERE action='docker_op' ORDER BY id DESC LIMIT 1"
        ).fetchall()
    finally:
        conn.close()
    assert rows and "web" in rows[0][1] and "restart" in rows[0][1]

    assert client.post("/api/docker/containers/ghost/start", headers=_admin(client)).status_code == 404
    assert client.post("/api/docker/containers/web/reboot", headers=_admin(client)).status_code == 400


def test_05_mask_env_unit():
    assert svc.mask_env(["A=1", "MY_TOKEN=x", "db_pass=y", "NOVALUE="]) == [
        "A=1", "MY_TOKEN=******", "db_pass=******", "NOVALUE=",
    ]
