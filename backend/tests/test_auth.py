"""P1 测试关卡：认证与账户（dev-plan P1 单元测试）。

测试顺序即业务链路：未初始化 → 弱口令拒绝 → 初始化 → 重复初始化拒绝 →
登录失败/成功 → me → refresh → 改密（旧 token 失效）→ 新密码登录 → 限速锁定。
"""

import asyncio as _asyncio

from fastapi.testclient import TestClient

from app.core.ratelimit import reset as reset_ratelimit

ADMIN_USER = "admin"
ADMIN_PASS = "portal123"
NEW_PASS = "portal456x"

_tokens: dict = {}  # 跨步骤共享签发的 token


def _auth(client: TestClient, token: str):
    return {"Authorization": f"Bearer {token}"}


def test_01_me_without_token(client: TestClient):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == 1002


def test_02_health_shows_not_initialized(client: TestClient):
    assert client.get("/api/health").json()["data"]["initialized"] is False


def test_03_init_weak_password_rejected(client: TestClient):
    resp = client.post("/api/auth/init", json={"username": "admin", "password": "short"})
    assert resp.status_code == 422


def test_04_init_creates_admin(client: TestClient):
    resp = client.post(
        "/api/auth/init",
        json={"username": ADMIN_USER, "password": ADMIN_PASS, "site_name": "My Portal"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["user"]["role"] == "admin"
    assert data["access_token"] and data["refresh_token"]
    _tokens["access"] = data["access_token"]
    _tokens["refresh"] = data["refresh_token"]


def test_05_init_again_rejected(client: TestClient):
    resp = client.post("/api/auth/init", json={"username": "root", "password": ADMIN_PASS})
    assert resp.json()["code"] == 1005


def test_06_login_wrong_password(client: TestClient):
    _asyncio.run(reset_ratelimit("testclient"))
    resp = client.post("/api/auth/login", json={"username": ADMIN_USER, "password": "wrong-pass1"})
    assert resp.json()["code"] == 1001


def test_07_login_ok(client: TestClient):
    _asyncio.run(reset_ratelimit("testclient"))
    resp = client.post("/api/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["user"]["username"] == ADMIN_USER
    _tokens["access2"] = data["access_token"]  # 改密前的 access，用于验证失效


def test_08_me_with_token(client: TestClient):
    resp = client.get("/api/auth/me", headers=_auth(client, _tokens["access2"]))
    assert resp.status_code == 200
    assert resp.json()["data"]["username"] == ADMIN_USER


def test_09_me_without_token_still_401(client: TestClient):
    assert client.get("/api/auth/me").status_code == 401


def test_10_refresh_ok(client: TestClient):
    resp = client.post("/api/auth/refresh", headers=_auth(client, _tokens["refresh"]))
    assert resp.status_code == 200
    assert resp.json()["data"]["access_token"]


def test_11_change_password_weak_rejected(client: TestClient):
    resp = client.put(
        "/api/auth/password",
        headers=_auth(client, _tokens["access2"]),
        json={"old_password": ADMIN_PASS, "new_password": "nodigit"},
    )
    assert resp.status_code == 422


def test_12_change_password_wrong_old(client: TestClient):
    resp = client.put(
        "/api/auth/password",
        headers=_auth(client, _tokens["access2"]),
        json={"old_password": "wrong-old1", "new_password": NEW_PASS},
    )
    assert resp.json()["code"] == 1001


def test_13_change_password_ok(client: TestClient):
    resp = client.put(
        "/api/auth/password",
        headers=_auth(client, _tokens["access2"]),
        json={"old_password": ADMIN_PASS, "new_password": NEW_PASS},
    )
    assert resp.status_code == 200


def test_14_old_access_token_invalidated(client: TestClient):
    """改密后：改密前签发的 access 与 refresh 均失效（M01-4）。"""
    resp = client.get("/api/auth/me", headers=_auth(client, _tokens["access2"]))
    assert resp.json()["code"] == 1003
    resp = client.post("/api/auth/refresh", headers=_auth(client, _tokens["refresh"]))
    assert resp.json()["code"] == 1003


def test_15_login_with_new_password(client: TestClient):
    _asyncio.run(reset_ratelimit("testclient"))
    resp = client.post("/api/auth/login", json={"username": ADMIN_USER, "password": NEW_PASS})
    assert resp.status_code == 200


def test_16_login_rate_limited(client: TestClient):
    """连续失败 5 次 → 锁定 1006（M01-6）。"""
    _asyncio.run(reset_ratelimit("testclient"))
    codes = []
    for _ in range(6):
        payload = {"username": ADMIN_USER, "password": "bad-pass9"}
        resp = client.post("/api/auth/login", json=payload)
        codes.append(resp.json()["code"])
    assert codes[:5] == [1001, 1001, 1001, 1001, 1001]
    assert codes[5] == 1006
    _asyncio.run(reset_ratelimit("testclient"))
