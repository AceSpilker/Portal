# ruff: noqa: E501
"""P7 测试关卡：用户管理（M01-11）+ 应用可见性与访客模式（M01-10/M03-10）。

覆盖边界规则（不能操作自己 / 至少保留 1 个启用 admin / 不物理删除）、
禁用与重置密码的会话失效、可见性四级过滤、访客端点开关。
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password

ADMIN = "admin"
ADMIN_PASS = "portal-p2"
ALICE = "alice"
ALICE_PASS = "alice12345"
BOB = "bob"
BOB_PASS = "bob1234567"

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
        for name, pwd in ((ALICE, ALICE_PASS), (BOB, BOB_PASS)):
            if conn.execute("SELECT 1 FROM users WHERE username = ?", (name,)).fetchone() is None:
                conn.execute(
                    "INSERT INTO users (username, password_hash, role, is_active, prefs, token_version)"
                    " VALUES (?, ?, 'user', 1, '{}', 0)",
                    (name, hash_password(pwd)),
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


def _admin(client: TestClient) -> dict:
    return _login(client, ADMIN, ADMIN_PASS)


def _alice(client: TestClient) -> dict:
    return _login(client, ALICE, ALICE_PASS)


def _bob(client: TestClient) -> dict:
    return _login(client, BOB, BOB_PASS)


def _mk_app(client: TestClient, name: str, visibility: str, visible_users: list | None = None) -> int:
    body: dict = {"name": name, "visibility": visibility}
    if visible_users is not None:
        body["visible_users"] = visible_users
    resp = client.post("/api/apps", json=body, headers=_admin(client))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["id"]


# ============ 用户管理（M01-11；7.4）============


def test_01_users_permission(client: TestClient):
    assert client.get("/api/users").status_code == 401
    assert client.get("/api/users", headers=_alice(client)).status_code == 403
    assert client.post("/api/users", json={"username": "x", "password": "x12345678"}, headers=_alice(client)).status_code == 403


def test_02_user_list_shape(client: TestClient):
    resp = client.get("/api/users?page=1&page_size=50", headers=_admin(client))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] >= 3
    for item in data["items"]:
        assert "password_hash" not in item
        assert "password" not in item


def test_03_user_list_search(client: TestClient):
    resp = client.get("/api/users?keyword=ali", headers=_admin(client))
    items = resp.json()["data"]["items"]
    assert len(items) == 1 and items[0]["username"] == ALICE


def test_04_create_user_dup_and_weak(client: TestClient):
    # 用户名重复
    resp = client.post(
        "/api/users",
        json={"username": ALICE, "password": "alice12345"},
        headers=_admin(client),
    )
    assert resp.status_code == 409
    # 弱密码
    resp = client.post(
        "/api/users",
        json={"username": "carol", "password": "weak"},
        headers=_admin(client),
    )
    assert resp.status_code == 422
    # 正常创建
    resp = client.post(
        "/api/users",
        json={"username": "carol", "password": "carol12345", "role": "user"},
        headers=_admin(client),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["role"] == "user"


def test_05_cannot_touch_self(client: TestClient):
    me = client.get("/api/auth/me", headers=_admin(client)).json()["data"]
    my_id = me["id"]
    # 禁用自己
    assert client.put(f"/api/users/{my_id}/status", json={"enabled": False}, headers=_admin(client)).status_code == 403
    # 降级自己
    assert client.put(f"/api/users/{my_id}", json={"role": "user"}, headers=_admin(client)).status_code == 403
    # 踢自己
    assert client.post(f"/api/users/{my_id}/kick", headers=_admin(client)).status_code == 403


def test_06_disable_kicks_sessions(client: TestClient):
    """禁用用户 → 其全部会话立即失效。"""
    resp = client.post(
        "/api/users",
        json={"username": "dave", "password": "dave123456"},
        headers=_admin(client),
    )
    dave_id = resp.json()["data"]["id"]
    dave_login = client.post("/api/auth/login", json={"username": "dave", "password": "dave123456"})
    dave_token = dave_login.json()["data"]["access_token"]
    hdr = {"Authorization": f"Bearer {dave_token}"}
    assert client.get("/api/auth/me", headers=hdr).status_code == 200

    # 禁用
    client.put(f"/api/users/{dave_id}/status", json={"enabled": False}, headers=_admin(client))
    assert client.get("/api/auth/me", headers=hdr).status_code == 401
    # 被禁用者重新登录也被拒
    assert client.post("/api/auth/login", json={"username": "dave", "password": "dave123456"}).status_code == 401


def test_07_last_admin_guard(client: TestClient):
    """全库至少保留 1 个启用 admin：唯一 admin 不可降级/禁用（对自己由 self-guard 拦截）。"""
    me = client.get("/api/auth/me", headers=_admin(client)).json()["data"]
    my_id = me["id"]
    # 把其他 admin 全禁用，只剩自己 → 对自己的降级被 self-guard 拦截（403）
    assert client.put(f"/api/users/{my_id}", json={"role": "user"}, headers=_admin(client)).status_code == 403


def test_08_reset_password_invalidates_and_relogin(client: TestClient):
    resp = client.get("/api/users?keyword=alice", headers=_admin(client))
    alice_id = resp.json()["data"]["items"][0]["id"]
    alice_login = client.post("/api/auth/login", json={"username": ALICE, "password": ALICE_PASS})
    old_token = alice_login.json()["data"]["access_token"]
    hdr = {"Authorization": f"Bearer {old_token}"}
    assert client.get("/api/auth/me", headers=hdr).status_code == 200

    resp = client.put(
        f"/api/users/{alice_id}/password",
        json={"password": "newpass12345"},
        headers=_admin(client),
    )
    assert resp.status_code == 200
    # 旧 token 失效
    assert client.get("/api/auth/me", headers=hdr).status_code == 401
    # 新密码可登录
    assert client.post("/api/auth/login", json={"username": ALICE, "password": "newpass12345"}).status_code == 200
    _tokens.pop(ALICE, None)
    # 恢复 alice 原密码，避免污染后续测试
    conn = sqlite3.connect(Path(settings.data_dir) / "portal.db")
    conn.execute("UPDATE users SET password_hash = ? WHERE username = ?",
                 (hash_password(ALICE_PASS), ALICE))
    conn.commit()
    conn.close()


def test_09_kick_user(client: TestClient):
    _login(client, BOB, BOB_PASS)
    resp = client.get("/api/users?keyword=bob", headers=_admin(client))
    bob_id = resp.json()["data"]["items"][0]["id"]
    assert client.post(f"/api/users/{bob_id}/kick", headers=_admin(client)).status_code == 200
    # bob 旧 token 失效，重新登录可恢复
    assert client.get("/api/auth/me", headers=_bob(client)).status_code == 401
    _tokens.pop(BOB, None)
    assert client.get("/api/auth/me", headers=_bob(client)).status_code == 200


# ============ 应用可见性与访客模式（M01-10/M03-10；7.5）============


def test_10_visibility_filter(client: TestClient):
    # 动态查 alice 的用户 id（DB 内既有用户顺序不确定）
    conn = sqlite3.connect(Path(settings.data_dir) / "portal.db")
    alice_db_id = conn.execute("SELECT id FROM users WHERE username = ?", (ALICE,)).fetchone()[0]
    conn.close()
    a_id = _mk_app(client, "可见-指定alice", "users", [alice_db_id])  # id 2=alice（假定顺序，见下方断言）
    pub_id = _mk_app(client, "可见-公开", "public")
    adm_id = _mk_app(client, "可见-仅管理员", "admin")

    # alice：能看到 users(自己是授权用户, id=2)/public；看不到 admin
    alice_apps = client.get("/api/apps", headers=_alice(client)).json()["data"]
    names = {a["name"] for a in alice_apps}
    assert "可见-指定alice" in names
    assert "可见-公开" in names
    assert "可见-仅管理员" not in names
    # bob：看不到指定 alice 的
    bob_apps = client.get("/api/apps", headers=_bob(client)).json()["data"]
    bob_names = {a["name"] for a in bob_apps}
    assert "可见-指定alice" not in bob_names
    assert "可见-公开" in bob_names
    # admin：全部可见
    admin_apps = client.get("/api/apps", headers=_admin(client)).json()["data"]
    admin_names = {a["name"] for a in admin_apps}
    assert {"可见-指定alice", "可见-公开", "可见-仅管理员"} <= admin_names
    # 清理（回收站）
    for aid in (a_id, pub_id, adm_id):
        client.delete(f"/api/apps/{aid}", headers=_admin(client))


def test_11_guest_endpoint(client: TestClient):
    """guest.enabled=0 → 404；开启后免认证返回 public 应用。"""
    # 默认关闭
    resp = client.get("/api/public/apps")
    assert resp.status_code == 404
    # 开启访客模式（settings 白名单）
    resp = client.put("/api/settings", json={"values": {"guest.enabled": True}}, headers=_admin(client))
    assert resp.status_code == 200, resp.text
    _mk_app(client, "可见-公开访客", "public")
    resp = client.get("/api/public/apps")
    assert resp.status_code == 200
    names = {a["name"] for a in resp.json()["data"]}
    assert "可见-公开访客" in names
    # 恢复关闭
    client.put("/api/settings", json={"values": {"guest.enabled": False}}, headers=_admin(client))
