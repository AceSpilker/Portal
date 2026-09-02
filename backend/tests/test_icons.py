"""图标库 v2 测试：内置/自定义统一实体（播种、改名级联、软删不复活、引用保护）。

文件名字母序在 test_crypto 之后、test_p2_apps 之前执行；
沿用 sqlite3 直改库重置 admin 密码的解耦模式。
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


def _seed(client: TestClient, names: list[str]) -> int:
    resp = client.post("/api/icons/seed", json={"names": names}, headers=_admin(client))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["seeded"]


def test_01_requires_auth(client: TestClient):
    assert client.get("/api/icons").status_code == 401
    assert client.post("/api/icons/seed", json={"names": ["Bell"]}).status_code == 401


def test_02_seed_builtin(client: TestClient):
    """播种内置图标：首次插入；重复播种不插入（seeded=0）。"""
    assert _seed(client, ["Bell", "Brush", "Calendar"]) == 3
    assert _seed(client, ["Bell", "Brush", "Calendar"]) == 0
    icons = {i["name"]: i for i in client.get("/api/icons", headers=_admin(client)).json()["data"]}
    assert icons["Bell"]["source"] == "builtin"
    assert icons["Bell"]["element_name"] == "Bell"


def test_03_upload_custom_icon(client: TestClient):
    raw = base64.b64encode(_png_bytes(300, 200, (255, 0, 0, 255))).decode()
    resp = client.post(
        "/api/icons",
        json={"name": "qBittorrent", "filename": "qb.png", "data": raw},
        headers=_admin(client),
    )
    assert resp.status_code == 200, resp.text
    icon = resp.json()["data"]
    assert icon["source"] == "custom" and icon["path"].startswith("/icons/")
    f = Path(settings.data_dir) / "icons" / Path(icon["path"]).name
    assert f.is_file()
    with Image.open(f) as im:
        assert im.size == (128, 128)  # 压方


def test_04_rename_builtin_cascades(client: TestClient):
    """内置图标改名：引用它的应用 icon 字段同步更新。"""
    icons = {i["name"]: i for i in client.get("/api/icons", headers=_admin(client)).json()["data"]}
    bell_id = icons["Bell"]["id"]
    app = client.post(
        "/api/apps",
        json={"name": "BellApp", "icon": "Bell", "icon_type": "element", "tags": []},
        headers=_admin(client),
    ).json()["data"]
    resp = client.put(
        f"/api/icons/{bell_id}", json={"name": "BellX"}, headers=_admin(client)
    )
    assert resp.status_code == 200
    detail = client.get(f"/api/apps/{app['id']}", headers=_admin(client)).json()["data"]
    assert detail["icon"] == "BellX"  # 引用级联更新


def test_05_delete_builtin_soft_no_resurrection(client: TestClient):
    """内置图标删除 = 软删；重新播种不复活。"""
    icons = {i["name"]: i for i in client.get("/api/icons", headers=_admin(client)).json()["data"]}
    cal_id = icons["Calendar"]["id"]
    assert client.delete(f"/api/icons/{cal_id}", headers=_admin(client)).status_code == 200
    names = [i["name"] for i in client.get("/api/icons", headers=_admin(client)).json()["data"]]
    assert "Calendar" not in names
    assert _seed(client, ["Calendar"]) == 0  # 不复活
    names = [i["name"] for i in client.get("/api/icons", headers=_admin(client)).json()["data"]]
    assert "Calendar" not in names


def test_06_edit_and_delete_custom(client: TestClient):
    """自定义图标：改名 → 删除（文件清理）。"""
    raw = base64.b64encode(_png_bytes(32, 32, (0, 128, 0, 255))).decode()
    icon = client.post(
        "/api/icons", json={"name": "temp-icon", "data": raw}, headers=_admin(client)
    ).json()["data"]
    resp = client.put(
        f"/api/icons/{icon['id']}", json={"name": "temp-icon-2"}, headers=_admin(client)
    )
    assert resp.json()["data"]["name"] == "temp-icon-2"
    resp = client.delete(f"/api/icons/{icon['id']}", headers=_admin(client))
    assert resp.status_code == 200
    names = [i["name"] for i in client.get("/api/icons", headers=_admin(client)).json()["data"]]
    assert "temp-icon-2" not in names


def test_07_delete_referenced_custom_blocked(client: TestClient):
    raw = base64.b64encode(_png_bytes(32, 32, (0, 0, 255, 255))).decode()
    icon = client.post(
        "/api/icons", json={"name": "used-icon", "data": raw}, headers=_admin(client)
    ).json()["data"]
    client.post(
        "/api/apps",
        json={"name": "UsesCustom", "icon": icon["path"], "icon_type": "upload", "tags": []},
        headers=_admin(client),
    )
    resp = client.delete(f"/api/icons/{icon['id']}", headers=_admin(client))
    assert resp.json()["code"] == 4003
    assert "1" in resp.json()["message"]
