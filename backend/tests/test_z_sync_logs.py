# ruff: noqa: E501
"""同步/连接事件日志（088）：MySQL 推送埋点、Redis 测试埋点、sync_logs 查询端点。
文件名 z 前缀：字母序置于 test_auth/test_crypto 之后（auth 链路要求全新库）。"""

import time

import pytest

ADMIN = "admin"
ADMIN_PASS = "portal-p11"
_tokens: dict = {}


def _reset_db_state() -> None:
    import sqlite3
    from pathlib import Path

    from app.core.config import settings
    from app.core.security import hash_password

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
def _setup(client):
    _reset_db_state()
    _tokens.clear()


def _admin(client) -> dict:
    if ADMIN not in _tokens:
        resp = client.post("/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASS})
        assert resp.status_code == 200, resp.text
        _tokens[ADMIN] = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {_tokens[ADMIN]}"}


def _logs(client, kind: str) -> list[dict]:
    resp = client.get(f"/api/sync-logs?kind={kind}&limit=50", headers=_admin(client))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["items"]


def _wait_log(client, kind: str, action: str, tries: int = 20) -> dict | None:
    for _ in range(tries):
        for it in _logs(client, kind):
            if it["action"] == action:
                return it
        time.sleep(0.1)
    return None


def test_01_push_recorded(client):
    """立即推送会记 push 日志（状态取决于配置：未启用=info，配置了假主机=failed）。"""
    resp = client.post("/api/sync/push", headers=_admin(client))
    assert resp.status_code == 200, resp.text
    row = _wait_log(client, "mysql", "push")
    assert row is not None, "push 未记日志"
    assert row["status"] in ("info", "failed", "ok") and row["message"]


def test_02_redis_test_failure_recorded(client):
    """Redis 连接测试失败（不可达地址）：记 test/failed 与错误消息。"""
    resp = client.post(
        "/api/redis/test",
        json={"host": "127.0.0.1", "port": 4999, "db": 0},
        headers=_admin(client),
    )
    assert resp.status_code == 200, resp.text
    row = _wait_log(client, "redis", "test")
    assert row is not None, "test 未记日志"
    assert row["status"] == "failed" and row["message"] != ""
    assert row["duration_ms"] >= 0


def test_03_kind_filter_and_shape(client):
    """kind 筛选互不串台；条目字段完整。"""
    items = _logs(client, "mysql")
    assert all(it["kind"] == "mysql" for it in items)
    for it in _logs(client, "redis"):
        assert it["kind"] == "redis"
    for it in _logs(client, "mysql") + _logs(client, "redis"):
        assert {"id", "kind", "action", "status", "duration_ms", "message", "created_at"} <= set(it)
