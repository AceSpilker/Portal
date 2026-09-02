"""P4 测试关卡：首页仪表盘后端（布局持久化 / 收藏 / 壁纸设置键）。

沿用 P2/P3 的测试基建（admin/alice 直改库重置）。
覆盖 dev-plan P4 单测关卡的后端部分：布局序列化 round-trip（保存/读取/用户隔离/整份覆盖）；
收藏切换权限与幂等；壁纸键白名单与取值范围。
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password

ADMIN_USER = "admin"
ADMIN_PASS = "portal-p2"
ALICE_USER = "alice"
ALICE_PASS = "alice12345"

_ids: dict = {}
_tokens: dict = {}


def _reset_db_state() -> None:
    """同步 sqlite3 直改库：确保 admin/alice 账号可用（同 test_p2_apps）。"""
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
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (ALICE_USER,)).fetchone() is None:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, is_active, prefs, token_version)"
                " VALUES (?, ?, 'user', 1, '{}', 0)",
                (ALICE_USER, hash_password(ALICE_PASS)),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="module", autouse=True)
def _setup(client: TestClient):
    _reset_db_state()
    _tokens.clear()


def _admin(client: TestClient) -> dict:
    if "admin" not in _tokens:
        resp = client.post("/api/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
        assert resp.status_code == 200, resp.text
        _tokens["admin"] = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {_tokens['admin']}"}


def _alice(client: TestClient) -> dict:
    if "alice" not in _tokens:
        resp = client.post("/api/auth/login", json={"username": ALICE_USER, "password": ALICE_PASS})
        assert resp.status_code == 200, resp.text
        _tokens["alice"] = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {_tokens['alice']}"}


def _make_apps(client: TestClient, names: list[str]) -> list[int]:
    ids = []
    for name in names:
        resp = client.post("/api/apps", json={"name": name}, headers=_admin(client))
        assert resp.status_code == 200, resp.text
        ids.append(resp.json()["data"]["id"])
    return ids


# ============ 布局持久化（M02-2；P4.2）============


def test_01_layouts_requires_auth(client: TestClient):
    assert client.get("/api/me/layouts").status_code == 401
    assert client.put("/api/me/layouts", json={"tab": "default", "layout": {}}).status_code == 401


def test_02_layout_roundtrip_and_isolation(client: TestClient):
    """保存 → 读取一致；用户间隔离；重复保存为整份覆盖（序列化 round-trip）。"""
    app_ids = _make_apps(client, ["布局应用A", "布局应用B", "布局应用C"])
    _ids["apps"] = app_ids
    # JSON 对象键约定为字符串（JS 侧天然字符串键）
    layout = {
        "order": [app_ids[2], app_ids[0], app_ids[1]],
        "sizes": {str(app_ids[2]): 2},
        "collapsed": {"1": True},
    }
    resp = client.put("/api/me/layouts", json={"tab": "default", "layout": layout},
                      headers=_admin(client))
    assert resp.status_code == 200, resp.text
    data = client.get("/api/me/layouts", headers=_admin(client)).json()["data"]
    assert len(data) == 1
    assert data[0]["tab"] == "default"
    assert data[0]["layout"] == layout  # round-trip 一致（含嵌套 dict/list）
    # alice 有自己独立的布局（空）
    assert client.get("/api/me/layouts", headers=_alice(client)).json()["data"] == []
    # admin 再次保存 → 覆盖而非新增
    layout2 = {"order": list(reversed(layout["order"])), "sizes": {}, "collapsed": {}}
    resp = client.put(
        "/api/me/layouts", json={"tab": "default", "layout": layout2}, headers=_admin(client)
    )
    assert resp.status_code == 200, resp.text
    data = client.get("/api/me/layouts", headers=_admin(client)).json()["data"]
    assert len(data) == 1 and data[0]["layout"] == layout2


def test_03_layout_validation(client: TestClient):
    resp = client.put("/api/me/layouts", json={"tab": "bad tab!", "layout": {}},
                      headers=_admin(client))
    assert resp.status_code == 422


# ============ 收藏（M02-9；P4.5）============


def test_04_favorite_requires_auth(client: TestClient):
    app_id = _ids["apps"][0]
    assert client.post(f"/api/apps/{app_id}/favorite").status_code == 401


def test_05_favorite_toggle_any_user(client: TestClient):
    """收藏为 A 权限：普通用户亦可收藏可见应用；幂等切换。"""
    app_id = _ids["apps"][0]
    resp = client.post(f"/api/apps/{app_id}/favorite", headers=_alice(client))
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["favorite"] is True
    assert client.post(f"/api/apps/{app_id}/favorite", headers=_alice(client)).json()["data"][
        "favorite"
    ] is False


# ============ 壁纸设置键（M02-20；P4.6）============


def test_06_wallpaper_settings_roundtrip(client: TestClient):
    values = {
        "appearance.wallpaper_type": "image",
        "appearance.wallpaper_value": "https://nas.local/wall.jpg",
        "appearance.wallpaper_blur": 6,
        "appearance.wallpaper_mask": 50,
    }
    resp = client.put("/api/settings", json={"values": values}, headers=_admin(client))
    assert resp.status_code == 200, resp.text
    data = client.get("/api/settings", headers=_alice(client)).json()["data"]
    for key, value in values.items():
        assert data[key] == value


def test_07_wallpaper_settings_validation(client: TestClient):
    # 类型不合法
    resp = client.put(
        "/api/settings", json={"values": {"appearance.wallpaper_type": "video"}},
        headers=_admin(client),
    )
    assert resp.status_code == 422
    # 范围不合法（blur ≤20 / mask ≤90）
    assert client.put(
        "/api/settings", json={"values": {"appearance.wallpaper_blur": 50}}, headers=_admin(client)
    ).status_code == 422
    assert client.put(
        "/api/settings", json={"values": {"appearance.wallpaper_mask": 95}}, headers=_admin(client)
    ).status_code == 422
    # 普通用户不可写
    assert client.put(
        "/api/settings", json={"values": {"appearance.wallpaper_type": "solid"}},
        headers=_alice(client),
    ).status_code == 403
