# ruff: noqa: E501
"""P22 测试关卡：企业登录 / 远期功能点子集（M01-12/13 等；dev-plan 22.1~22.3）。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password

ADMIN = "admin"
ADMIN_PASS = "portal-p22"

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


def test_01_oidc_authorize_and_callback(client: TestClient, monkeypatch):
    """OIDC（22.1）：未配置 404 → 配置后 authorize URL → callback 换取会话并自动开通。"""
    h = _admin(client)
    assert client.get("/api/auth/oidc/authorize", headers=h).status_code == 404
    client.put("/api/auth/enterprise", json={
        "oidc_enabled": True, "oidc_issuer": "https://idp.example.com",
        "oidc_client_id": "portal", "oidc_client_secret": "sec",
    }, headers=h)
    authz = client.get("/api/auth/oidc/authorize", headers=h).json()["data"]
    assert "response_type=code" in authz["authorize_url"] and authz["state"]

    # mock httpx：token + userinfo
    import httpx as _httpx

    class FakeResp:
        status_code = 200

        def json(self):
            return self._j

        def raise_for_status(self):
            pass

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **k):
            r = FakeResp()
            r._j = {"access_token": "at"}
            return r

        async def get(self, url, **k):
            r = FakeResp()
            r._j = {"preferred_username": "oidcuser", "sub": "u1"}
            return r

    monkeypatch.setattr(_httpx, "AsyncClient", FakeClient)
    cb = client.post("/api/auth/oidc/callback", json={"code": "abc"})
    assert cb.status_code == 200, cb.text
    data = cb.json()["data"]
    assert data["user"]["username"] == "oidcuser" and data["access_token"]
    # 再次回调：同一用户不重复开通
    cb2 = client.post("/api/auth/oidc/callback", json={"code": "abc"})
    assert cb2.json()["data"]["user"]["username"] == "oidcuser"


def test_02_ldap_login(client: TestClient, monkeypatch):
    """LDAP（22.1）：绑定成功自动开通；绑定失败 401；未启用 404。"""
    h = _admin(client)
    body = {"username": "ldapuser", "password": "x"}
    assert client.post("/api/auth/ldap/login", json=body).status_code == 404  # 未启用
    client.put("/api/auth/enterprise", json={"ldap_enabled": True, "ldap_server": "ldap://x"}, headers=h)

    import ldap3 as _ldap3

    class _Ok:
        def unbind(self):
            pass

    monkeypatch.setattr(_ldap3, "Server", lambda *a, **k: None)
    monkeypatch.setattr(_ldap3, "Connection", lambda *a, **k: _Ok())
    ok_login = client.post("/api/auth/ldap/login", json={"username": "ldapuser", "password": "x"})
    assert ok_login.status_code == 200 and ok_login.json()["data"]["user"]["username"] == "ldapuser"
    # 绑定失败（Connection 构造抛错）→ 401
    def boom(*a, **k):
        raise RuntimeError("bind failed")
    monkeypatch.setattr(_ldap3, "Connection", boom)
    fail = client.post("/api/auth/ldap/login", json={"username": "ldapuser", "password": "x"})
    assert fail.status_code == 401


def test_03_recent_apps(client: TestClient):
    """最近使用（22.2/M02-8）：opened 标记 → recent 列表排序。"""
    h = _admin(client)
    a = client.post("/api/apps", json={"name": "最近A"}, headers=h).json()["data"]["id"]
    b = client.post("/api/apps", json={"name": "最近B"}, headers=h).json()["data"]["id"]
    client.post(f"/api/apps/{a}/opened", headers=h)
    import time as _t

    _t.sleep(0.05)
    client.post(f"/api/apps/{b}/opened", headers=h)
    recent = client.get("/api/apps/recent", headers=h).json()["data"]
    assert [x["name"] for x in recent][:2] == ["最近B", "最近A"]
    client.delete(f"/api/apps/{a}/purge", headers=h)
    client.delete(f"/api/apps/{b}/purge", headers=h)


def test_04_calendar_ics(client: TestClient):
    """日历订阅（22.2/M13-6）：ICS 输出 VEVENT 与转义。"""
    h = _admin(client)
    eid = client.post("/api/calendar/events", json={"title": "带,逗号", "date": "2026-10-01"}, headers=h).json()["data"]["id"]
    ics = client.get("/api/calendar/ics", headers=h).json()["data"]
    assert "BEGIN:VCALENDAR" in ics and "带\\,逗号" in ics and "END:VCALENDAR" in ics
    client.delete(f"/api/calendar/events/{eid}", headers=h)


def test_05_dns_tool(client: TestClient):
    """DNS 查询（22.2/M10-4）：localhost 解析返回 127.0.0.1。"""
    h = _admin(client)
    r = client.get("/api/tools/dns?host=localhost", headers=h).json()["data"]
    assert "127.0.0.1" in r["addresses"]
    empty = client.get("/api/tools/dns", headers=h)
    assert empty.status_code == 422  # host 必填


def test_06_ai_usage_shape(client: TestClient):
    """AI 用量统计（22.2/M05-15）形状。"""
    h = _admin(client)
    r = client.get("/api/ai/usage?days=7", headers=h).json()["data"]
    assert isinstance(r["days"], list)
