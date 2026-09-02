"""自定义图标管理测试（GET/POST/PUT/DELETE /api/icons）。

文件名字母序在 test_crypto 之后、test_p2_apps 之前执行；
沿用 sqlite3 直改库重置 admin 密码的解耦模式，可独立运行。
"""
import base64
import io
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import settings
from app.core.security import hash_password

ADMIN_USER = "admin"
ADMIN_PASS = "portal-icons"
_tokens: dict = {}


def _png_bytes(w: int, h: int, color) -> bytes:
    img = Image.new("RGBA", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


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
    _tokens.clear()


def _admin(client: TestClient) -> dict:
    if "admin" not in _tokens:
        resp = client.post("/api/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
        assert resp.status_code == 200, resp.text
        _tokens["admin"] = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {_tokens['admin']}"}


def test_01_requires_auth(client: TestClient):
    assert client.get("/api/icons").status_code == 401
    resp = client.post(
        "/api/icons",
        json={"name": "x", "data": base64.b64encode(_png_bytes(8, 8, (255, 0, 0, 255))).decode()},
    )
    assert resp.status_code == 401


def test_02_create_and_list(client: TestClient):
    raw = _png_bytes(300, 200, (255, 0, 0, 255))
    resp = client.post(
        "/api/icons",
        json={"name": "qBittorrent", "filename": "qb.png", "data": base64.b64encode(raw).decode()},
        headers=_admin(client),
    )
    assert resp.status_code == 200, resp.text
    icon = resp.json()["data"]
    assert icon["name"] == "qBittorrent"
    assert icon["path"].startswith("/icons/")
    # 压方为 128x128
    f = Path(settings.data_dir) / "icons" / Path(icon["path"]).name
    assert f.is_file()
    with Image.open(f) as im:
        assert im.size == (128, 128)

    names = [i["name"] for i in client.get("/api/icons", headers=_admin(client)).json()["data"]]
    assert "qBittorrent" in names


def test_03_duplicate_name(client: TestClient):
    raw = base64.b64encode(_png_bytes(16, 16, (0, 255, 0, 255))).decode()
    resp = client.post(
        "/api/icons",
        json={"name": "qBittorrent", "data": raw},
        headers=_admin(client),
    )
    assert resp.json()["code"] == 4002


def test_04_rename_and_replace_image(client: TestClient):
    icons = {i["name"]: i for i in client.get("/api/icons", headers=_admin(client)).json()["data"]}
    iid = icons["qBittorrent"]["id"]
    old_path = icons["qBittorrent"]["path"]

    raw = base64.b64encode(_png_bytes(64, 64, (0, 0, 255, 255))).decode()
    resp = client.put(
        f"/api/icons/{iid}",
        json={"name": "qb-2", "data": raw, "filename": "qb2.png"},
        headers=_admin(client),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["name"] == "qb-2"
    assert data["path"] != old_path  # 换图后为新文件


def test_05_delete_blocked_when_referenced(client: TestClient):
    icons = {i["name"]: i for i in client.get("/api/icons", headers=_admin(client)).json()["data"]}
    iid = icons["qb-2"]["id"]
    path = icons["qb-2"]["path"]
    # 应用引用该图标
    resp = client.post(
        "/api/apps",
        json={"name": "UsesIcon", "icon": path, "icon_type": "upload", "tags": []},
        headers=_admin(client),
    )
    assert resp.status_code == 200
    resp = client.delete(f"/api/icons/{iid}", headers=_admin(client))
    assert resp.json()["code"] == 4003
    assert "1 个应用/分组" in resp.json()["message"]


def test_06_delete_unused_ok(client: TestClient):
    raw = base64.b64encode(_png_bytes(16, 16, (128, 128, 0, 255))).decode()
    icon = client.post(
        "/api/icons", json={"name": "unused", "data": raw}, headers=_admin(client)
    ).json()["data"]
    resp = client.delete(f"/api/icons/{icon['id']}", headers=_admin(client))
    assert resp.status_code == 200
    names = [i["name"] for i in client.get("/api/icons", headers=_admin(client)).json()["data"]]
    assert "unused" not in names
    # 文件已清理
    f = Path(settings.data_dir) / "icons" / Path(icon["path"]).name
    assert not f.exists()


def test_07_not_found(client: TestClient):
    resp = client.put("/api/icons/99999", json={"name": "x"}, headers=_admin(client))
    assert resp.json()["code"] == 4001
    resp = client.delete("/api/icons/99999", headers=_admin(client))
    assert resp.json()["code"] == 4001
