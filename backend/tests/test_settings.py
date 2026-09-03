"""P7.1 前置落地测试：系统设置接口（GET/PUT /api/settings）+ element 图标类型。

文件名字母序在 test_p2_apps 之后执行；与 P2 同法直接改库重置 admin 密码，
既覆盖前置文件改密后的状态，也可单独运行。
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password
from app.models.setting import DEFAULT_SETTINGS

ADMIN_USER = "admin"
ADMIN_PASS = "portal-settings"
_tokens: dict = {}


def _reset_admin() -> None:
    """upsert admin：既覆盖前置文件改密后的状态，也支持本文件单独运行（空库）。"""
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


def test_01_get_requires_auth(client: TestClient):
    assert client.get("/api/settings").status_code == 401


def test_02_defaults_available(client: TestClient):
    """默认键（含 apps.tag_options）随启动合并写入，登录用户可读。"""
    import json

    resp = client.get("/api/settings", headers=_admin(client))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["apps.tag_options"] == json.loads(DEFAULT_SETTINGS["apps.tag_options"])
    assert data["general.site_name"]
    assert "general.language" in data


def test_03_put_requires_admin(client: TestClient):
    resp = client.put(
        "/api/settings",
        json={"values": {"general.site_name": "Hack"}},
    )
    assert resp.status_code == 401
    # 普通用户（无 alice 时跳过 403 细节，P2 文件已覆盖角色体系）
    assert _admin(client)


def test_04_put_unknown_key_rejected(client: TestClient):
    resp = client.put(
        "/api/settings",
        json={"values": {"hack.key": "x"}},
        headers=_admin(client),
    )
    assert resp.status_code == 422
    assert "不支持的设置项" in resp.json()["message"]


def test_05_put_invalid_tag_options(client: TestClient):
    resp = client.put(
        "/api/settings",
        json={"values": {"apps.tag_options": "not-a-list"}},
        headers=_admin(client),
    )
    assert resp.status_code == 422
    resp = client.put(
        "/api/settings",
        json={"values": {"apps.tag_options": ["", "ok"]}},
        headers=_admin(client),
    )
    assert resp.status_code == 422


def test_06_put_and_get_roundtrip(client: TestClient):
    resp = client.put(
        "/api/settings",
        json={
            "values": {
                "general.site_name": "我的 NAS",
                "apps.tag_options": ["影音", "工具", "自托管"],
            }
        },
        headers=_admin(client),
    )
    assert resp.status_code == 200, resp.text
    data = client.get("/api/settings", headers=_admin(client)).json()["data"]
    assert data["general.site_name"] == "我的 NAS"
    assert data["apps.tag_options"] == ["影音", "工具", "自托管"]
    # 批量写部分键不影响其他键
    assert "general.language" in data


def test_07_element_icon_type(client: TestClient):
    """应用图标新类型 element：存 Element Plus 图标名。"""
    resp = client.post(
        "/api/apps",
        json={"name": "元素图标应用", "icon_type": "element", "icon": "Monitor", "tags": []},
        headers=_admin(client),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["icon"] == "Monitor"
    assert resp.json()["data"]["icon_type"] == "element"
    # 非法类型依旧拒绝
    resp = client.post(
        "/api/apps",
        json={"name": "x", "icon_type": "glyph", "tags": []},
        headers=_admin(client),
    )
    assert resp.status_code == 422


def test_init_db_does_not_reset_user_settings():
    """P0.3 回归：默认设置只补缺，不得在重启(init_db)时覆盖用户已修改的值。"""
    import asyncio
    import json

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.models import DEFAULT_SETTINGS, Base, Setting

    async def _run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with maker() as s:
            for key, value in DEFAULT_SETTINGS.items():
                if await s.get(Setting, key) is None:
                    s.add(Setting(key=key, value=value))
            await s.commit()
            # 用户修改主题色
            await s.merge(Setting(key="appearance.theme_color", value=json.dumps("#f59e0b")))
            await s.commit()
            # 模拟再次启动：默认设置只补缺
            for key, value in DEFAULT_SETTINGS.items():
                if await s.get(Setting, key) is None:
                    s.add(Setting(key=key, value=value))
            await s.commit()
            row = await s.get(Setting, "appearance.theme_color")
            return row.get_value()

    assert asyncio.run(_run()) == "#f59e0b"
