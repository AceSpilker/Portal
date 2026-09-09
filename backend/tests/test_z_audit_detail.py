# ruff: noqa: E501
"""审计执行详情（087）：中间件拆列写入 method/path/status/duration/UA。
>=400 捕获统一响应 message；查询 API 返回 username 与新字段 + method 筛选。
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


def _find(client, path: str, tries: int = 20) -> dict | None:
    for _ in range(tries):
        items = client.get(
            "/api/audit-logs?range=all&page_size=200", headers=_admin(client)
        ).json()["data"]["items"]
        for it in items:
            if it["path"] == path:
                return it
        time.sleep(0.1)
    return None


def test_01_success_row_has_full_details(client):
    """成功写操作：method/path/status/duration_ms/UA 全部落库，query 为空。"""
    resp = client.post("/api/apps", json={"name": "audit-detail", "urls": []}, headers=_admin(client))
    assert resp.status_code == 200, resp.text
    app_id = resp.json()["data"]["id"]
    row = _find(client, "/api/apps")
    assert row is not None, "审计未落库"
    assert row["method"] == "POST"
    assert row["path"] == "/api/apps"
    assert row["status"] == 200
    assert row["duration_ms"] >= 0
    assert row["user_agent"] != ""
    assert row["error_msg"] == ""
    assert row["username"] == ADMIN
    client.delete(f"/api/apps/{app_id}", headers=_admin(client))


def test_02_error_row_captures_message(client):
    """422 校验失败：error_msg 捕获统一响应 message（如用户名已占用）。"""
    resp = client.post("/api/apps", json={}, headers=_admin(client))
    assert resp.status_code == 422
    row = _find(client, "/api/apps")
    assert row is not None and row["status"] == 422
    assert row["error_msg"] != "", "4xx 未捕获错误消息"


def test_03_method_filter_and_username(client):
    """method 筛选只回同方法记录；自己产生的审计行 username 为登录用户名。"""
    resp = client.post("/api/apps", json={"name": "audit-filter", "urls": []}, headers=_admin(client))
    assert resp.status_code == 200, resp.text
    app_id = resp.json()["data"]["id"]
    time.sleep(0.4)
    data = client.get(
        "/api/audit-logs?range=all&method=DELETE&page_size=200", headers=_admin(client)
    ).json()["data"]
    assert all(it["method"] == "DELETE" for it in data["items"])
    # 只断言本用例产生的行（全量套件下审计表含其他用例用户的数据）
    row = _find(client, "/api/apps")
    assert row is not None and row["username"] == ADMIN
    client.delete(f"/api/apps/{app_id}", headers=_admin(client))
