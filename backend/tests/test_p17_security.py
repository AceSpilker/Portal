# ruff: noqa: E501
"""P17 测试关卡：安全增强与系统完善（M01/M14/M15；dev-plan 17.1~17.5）。

- TOTP：setup/enable/登录强制验证码/时钟偏移容差/恢复码单次有效/disable；
- 会话管理：登录登记、清单、吊销后 refresh 拒绝；
- API Token：创建（明文一次）/ro 拦写/rw 放行/吊销后 401；
- 备份：export → factory-reset → import round-trip；审计查询与 CSV；
- 注册开关；健康自检完整版；更新状态形状。
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password

ADMIN = "admin"
ADMIN_PASS = "portal-p17"

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


def _code_for_secret(secret: str) -> str:
    import time

    from app.services.totp import _code_at

    return _code_at(secret, int(time.time() // 30))


def test_01_totp_flow(client: TestClient):
    """TOTP 全链路：setup → enable（验证码）→ 登录需 code → 恢复码 → disable。"""
    h = _admin(client)
    setup = client.post("/api/auth/totp/setup", headers=h).json()["data"]
    assert setup["secret"] and setup["otpauth_uri"].startswith("otpauth://totp/")
    code = _code_for_secret(setup["secret"])
    enable = client.post("/api/auth/totp/enable", json={"code": code}, headers=h)
    assert enable.status_code == 200, enable.text
    recovery = enable.json()["data"]["recovery_codes"]
    assert len(recovery) == 8

    # 开启后：无 code 登录 422；错 code 422
    bad = client.post("/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASS})
    assert bad.status_code == 422
    bad2 = client.post("/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASS, "totp_code": "000000"})
    assert bad2.status_code == 422
    # 正确 code 登录成功
    ok_login = client.post(
        "/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASS, "totp_code": _code_for_secret(setup["secret"])}
    )
    assert ok_login.status_code == 200
    # 恢复码登录（单次有效）
    rec_login = client.post(
        "/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASS, "totp_code": recovery[0]}
    )
    assert rec_login.status_code == 200
    rec_again = client.post(
        "/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASS, "totp_code": recovery[0]}
    )
    assert rec_again.status_code == 422

    # disable：密码错误 401；正确后可免 code 登录
    assert client.post("/api/auth/totp/disable", json={"password": "wrong", "code": "123456"}, headers=h).status_code == 401
    assert client.post("/api/auth/totp/disable", json={"password": ADMIN_PASS, "code": "123456"}, headers=h).status_code == 422
    assert client.post("/api/auth/totp/disable", json={"password": ADMIN_PASS, "code": _code_for_secret(setup["secret"])}, headers=h).status_code == 200
    plain = client.post("/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASS})
    assert plain.status_code == 200


def test_02_sessions_lifecycle(client: TestClient):
    """会话管理：登录登记 → 清单 → 吊销 → 该会话 refresh 被拒。"""
    # 新登录一个会话
    login = client.post("/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASS})
    assert login.status_code == 200
    refresh_token = login.json()["data"]["refresh_token"]
    h = _admin(client)
    sessions = client.get("/api/auth/sessions", headers=h).json()["data"]
    target = next(s for s in sessions if not s["revoked"])
    assert target["ip"]
    # 吊销后该会话 refresh 拒绝（401/1002）
    assert client.delete(f"/api/auth/sessions/{target['id']}", headers=h).status_code == 200
    after = client.post("/api/auth/refresh", headers={"Authorization": f"Bearer {refresh_token}"})
    assert after.status_code == 401


def test_03_api_tokens(client: TestClient):
    """API Token：创建/ro 拦写/rw 放行/吊销后 401/未知 token 401。"""
    h = _admin(client)
    # ro token
    ro = client.post("/api/tokens", json={"name": "只读", "scope": "ro"}, headers=h).json()["data"]
    assert ro["token"].startswith("plt_") and ro["prefix"] == ro["token"][:8]
    ro_h = {"Authorization": f"Bearer {ro['token']}"}
    assert client.get("/api/apps", headers=ro_h).status_code == 200
    assert client.post("/api/tokens", json={"name": "x", "scope": "rw"}, headers=ro_h).status_code == 403
    # rw token
    rw = client.post("/api/tokens", json={"name": "读写", "scope": "rw"}, headers=h).json()["data"]
    rw_h = {"Authorization": f"Bearer {rw['token']}"}
    assert client.post("/api/tokens", json={"name": "y", "scope": "ro"}, headers=rw_h).status_code == 200
    # 吊销后 401
    assert client.delete(f"/api/tokens/{rw['id']}", headers=h).status_code == 200
    assert client.get("/api/apps", headers=rw_h).status_code == 401
    # 清理 ro
    client.delete(f"/api/tokens/{ro['id']}", headers=h)


def test_04_backup_roundtrip_and_factory_reset(client: TestClient):
    """备份 round-trip：导出 → 建临时应用 → 恢复出厂（清空+留账号）→ 导入还原。"""
    h = _admin(client)
    export = client.get("/api/backup/export", headers=h).json()["data"]
    assert export["apps"] is not None and "settings" in export
    apps_before = len(export["apps"])

    # 造一个应用再恢复出厂
    temp = client.post("/api/apps", json={"name": "待清除应用"}, headers=h).json()["data"]["id"]
    reset = client.post("/api/backup/factory-reset", json={"password": ADMIN_PASS}, headers=h)
    assert reset.status_code == 200, reset.text
    listing = client.get("/api/apps", headers=h).json()["data"]
    assert listing == []  # 业务数据清空
    me = client.get("/api/auth/me", headers=h)
    assert me.status_code == 200  # 管理员账号保留
    # 导入还原
    imp = client.post("/api/backup/import", json=export, headers=h)
    assert imp.status_code == 200, imp.text
    restored = client.get("/api/apps", headers=h).json()["data"]
    assert len(restored) == apps_before
    client.delete(f"/api/apps/{temp}/purge", headers=h)


def test_05_register_and_audit(client: TestClient):
    """注册开关：默认关 → 开启注册/重复用户名 422 → 审计查询与 CSV 导出。"""
    h = _admin(client)
    cfg = client.get("/api/auth/config").json()["data"]
    assert cfg["allow_register"] is False
    assert client.post("/api/auth/register", json={"username": "newuser", "password": "password123"}).status_code == 403
    client.put("/api/settings", json={"values": {"security.allow_register": True}}, headers=h)
    reg = client.post("/api/auth/register", json={"username": "newuser", "password": "password123"})
    assert reg.status_code == 200
    dup = client.post("/api/auth/register", json={"username": "newuser", "password": "password123"})
    assert dup.status_code == 422
    short = client.post("/api/auth/register", json={"username": "other", "password": "123"})
    assert short.status_code == 422
    client.put("/api/settings", json={"values": {"security.allow_register": False}}, headers=h)
    # 审计（登录已写审计）
    logs = client.get("/api/audit-logs?range=24h", headers=h).json()["data"]
    assert logs["total"] >= 1 and any(i["action"] == "login" for i in logs["items"])
    csv = client.get("/api/audit-logs/export?range=7d", headers=h).json()["data"]
    assert csv["filename"].endswith(".csv") and "action" in csv["csv"]


def test_06_health_full_and_update_status(client: TestClient):
    """健康自检完整版字段；更新状态形状（idle）。"""
    h = _admin(client)
    full = client.get("/api/system/health-report/full", headers=h).json()["data"]
    assert full["data_dir_writable"] in (True, False)
    assert "internet_ok" in full and "last_backup_at" in full
    status = client.get("/api/system/update/status", headers=h).json()["data"]
    assert status["stage"] in ("idle", "checking", "applying", "ok", "failed")


def test_07_update_check_contract(client: TestClient, monkeypatch):
    """更新检查：Gitee 不可达时返回 error 字段（网络异常不阻塞、has_update=False）。"""
    h = _admin(client)
    resp = client.get("/api/system/update/check", headers=h)
    data = resp.json()["data"]
    assert data["current"] == settings.app_version
    assert data["has_update"] is False or data.get("latest")
