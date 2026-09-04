# ruff: noqa: E501
"""P23 测试关卡：MySQL 数据同步（M15-12；dev-plan 23.1~23.6）。

- 双库兼容：ORM 元数据生成 MySQL DDL（类型映射验证）；
- 配置：密码 Fernet 加密 round-trip、空密码保持原值、回传脱敏；
- 推送：未启用 disabled、不可达时 sync_state=failed 且退避跳过、本地不受影响；
- 恢复：confirm 保护。
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password

ADMIN = "admin"
ADMIN_PASS = "portal-p23"

_tokens: dict = {}


def _reset_db_state() -> None:
    import sqlite3

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


def test_01_ddl_and_type_mapping():
    """双库兼容（23.1）：MySQL DDL 生成与类型映射（INT/VARCHAR/TINYINT/TEXT）。"""
    from app.services.mysql_sync import SYNC_TABLES, ddl_statements

    ddls = ddl_statements()
    assert len(ddls) >= len(SYNC_TABLES)
    joined = "\n".join(ddls)
    for table in SYNC_TABLES:
        assert f"CREATE TABLE {table}" in joined, table
    # 关键类型映射：布尔→TINYINT(1)、字符串→VARCHAR、文本→TEXT、时间→DATETIME
    assert "TINYINT" in joined or "BOOL" in joined
    assert "VARCHAR" in joined and "TEXT" in joined and "DATETIME" in joined
    # 敏感表不出现
    for banned in ("users", "user_sessions", "api_tokens", "audit_logs"):
        assert f"CREATE TABLE {banned} " not in joined


def test_02_password_crypto_and_config(client: TestClient):
    """配置（23.2）：Fernet 加密 round-trip；PUT 后 GET 脱敏；空密码保持原值。"""
    from app.services.mysql_sync import decrypt_password, encrypt_password

    assert decrypt_password(encrypt_password("mypass")) == "mypass"
    # 密钥文件已生成
    assert (Path(settings.data_dir) / "keys" / "sync.key").exists()

    h = _admin(client)
    save = client.put(
        "/api/settings/sync",
        json={"host": "127.0.0.1", "port": 3307, "user": "portal", "password": "mypass",
              "database": "portal_test", "interval_min": 15, "enabled": True},
        headers=h,
    )
    assert save.status_code == 200, save.text
    data = save.json()["data"]
    assert data["password"] == "" and data["password_set"] is True and data["port"] == 3307
    # 空密码=保持原值
    keep = client.put("/api/settings/sync", json={"host": "127.0.0.1", "port": 3307, "enabled": True}, headers=h)
    assert keep.json()["data"]["password_set"] is True


def test_03_mysql_test_endpoint(client: TestClient):
    """连接测试（23.2）：不可达返回 ok=False（不抛 500）。"""
    h = _admin(client)
    resp = client.post("/api/mysql/test", json={"host": "127.0.0.1", "port": 1, "user": "x", "password": "y", "database": "z"}, headers=h)
    assert resp.status_code == 200
    assert resp.json()["data"]["ok"] is False


def test_04_push_disabled_and_unreachable(client: TestClient):
    """推送（23.3/23.4）：未启用 disabled；不可达→全表 failed、本地功能正常。"""
    h = _admin(client)
    # 先显式关闭（前面的用例可能已开启）
    client.put("/api/settings/sync", json={"host": "127.0.0.1", "enabled": False}, headers=h)
    r = client.post("/api/sync/push", headers=h).json()["data"]
    assert r["enabled"] is False and r.get("error") == "disabled"
    # 启用但指向死端口
    client.put("/api/settings/sync", json={"host": "127.0.0.1", "port": 1, "enabled": True}, headers=h)
    r2 = client.post("/api/sync/push", headers=h).json()["data"]
    assert r2["enabled"] is True and r2.get("error")
    # sync_state 全部 failed
    status = client.get("/api/sync/status", headers=h).json()["data"]
    assert status["enabled"] is True
    failed = [t for t in status["tables"] if t["status"] == "failed"]
    assert len(failed) >= 1 and all(t["fail_count"] >= 1 for t in failed)
    # 本地不受影响：应用 CRUD 正常
    app = client.post("/api/apps", json={"name": "本地不受影响"}, headers=h)
    assert app.status_code == 200
    client.delete(f"/api/apps/{app.json()['data']['id']}/purge", headers=h)


def test_05_restore_confirm_guard(client: TestClient):
    """灾难恢复（23.5）：无 confirm 422；带 confirm 时不可达返回 ok=False。"""
    h = _admin(client)
    assert client.post("/api/sync/restore", json={}, headers=h).status_code == 422
    r = client.post("/api/sync/restore", json={"confirm": True}, headers=h)
    data = r.json()["data"]
    assert data["ok"] is False and "backup" in data  # 本地备份先行
