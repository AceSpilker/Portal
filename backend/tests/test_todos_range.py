"""待办日期区间测试（077）：起止日期创建/回显/校验。自举同 test_icons 模式。"""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password

ADMIN_USER = "admin"
ADMIN_PASS = "portal-todo"

_TOKEN_CACHE: dict = {}


def _reset_admin() -> None:
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
    _reset_admin()
    _TOKEN_CACHE.clear()


@pytest.fixture(autouse=True)
def _disable_login_lock(monkeypatch):
    import app.api.v1.auth as auth_mod

    async def _never_locked(_ip: str) -> bool:
        return False

    monkeypatch.setattr(auth_mod, "is_locked", _never_locked)


def _login(client: TestClient) -> str:
    if "token" not in _TOKEN_CACHE:
        resp = client.post(
            "/api/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}
        ).json()["data"]
        _TOKEN_CACHE["token"] = resp["access_token"]
    return _TOKEN_CACHE["token"]


def test_01_todo_with_range(client):
    """待办支持开始/结束日期，返回体回显区间。"""
    resp = client.post(
        "/api/todos",
        json={"title": "区间待办", "date": "2026-09-08", "end_date": "2026-09-12"},
        headers={"Authorization": f"Bearer {_login(client)}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["date"] == "2026-09-08" and data["end_date"] == "2026-09-12"
    # 清理
    client.delete(
        f"/api/todos/{data['id']}", headers={"Authorization": f"Bearer {_login(client)}"}
    )


def test_02_todo_range_reversed_rejected(client):
    """结束日期早于开始日期 → 422。"""
    resp = client.post(
        "/api/todos",
        json={"title": "倒置", "date": "2026-09-12", "end_date": "2026-09-08"},
        headers={"Authorization": f"Bearer {_login(client)}"},
    )
    assert resp.status_code == 422
