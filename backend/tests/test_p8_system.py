# ruff: noqa: E501
"""P8 测试关卡：健康自检基础版（M15-10 部分；dev-plan 8.2）。

- 权限：401 未登录 / 403 普通用户 / 200 管理员；
- 报告形状：数据卷可写、调度器运行、核心任务（app_probe/monitor_sample）在线；
- 容器场景由 docker compose healthcheck 打 /api/health（见仓库根 compose）。
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password

ADMIN = "admin"
ADMIN_PASS = "portal-p8"

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


def _login(client: TestClient, username: str, password: str) -> dict:
    key = username
    if key not in _tokens:
        resp = client.post("/api/auth/login", json={"username": username, "password": password})
        assert resp.status_code == 200, resp.text
        _tokens[key] = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {_tokens[key]}"}


def test_01_requires_auth(client: TestClient):
    resp = client.get("/api/system/health-report")
    assert resp.status_code == 401


def test_02_admin_only(client: TestClient, tmp_path):
    # 造一个普通用户验证 403
    db_file = Path(settings.data_dir) / "portal.db"
    conn = sqlite3.connect(db_file)
    try:
        if conn.execute("SELECT 1 FROM users WHERE username = 'peak8'").fetchone() is None:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, is_active, prefs, token_version)"
                " VALUES ('peak8', ?, 'user', 1, '{}', 0)",
                (hash_password("peak812345"),),
            )
        conn.commit()
    finally:
        conn.close()
    user_headers = _login(client, "peak8", "peak812345")
    assert client.get("/api/system/health-report", headers=user_headers).status_code == 403
    admin_headers = _login(client, ADMIN, ADMIN_PASS)
    assert client.get("/api/system/health-report", headers=admin_headers).status_code == 200


def test_03_report_shape_and_tasks(client: TestClient):
    resp = client.get("/api/system/health-report", headers=_login(client, ADMIN, ADMIN_PASS))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["data_dir_writable"] is True
    assert data["scheduler_running"] is True
    assert data["tasks_ok"] is True
    assert data["missing_tasks"] == []
    task_ids = {t["id"] for t in data["tasks"]}
    assert {"app_probe", "monitor_sample", "monitor_cleanup", "monitor_gpu"} <= task_ids
    for t in data["tasks"]:
        assert t["next_run_ts"] is not None
    assert isinstance(data["checked_at"], int)
