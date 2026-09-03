# ruff: noqa: E501
"""P15 测试关卡：应用与仪表盘增强（M03/M02/M04；dev-plan 15.1~15.4）。

- 回收站恢复（restore/purge/列表）；
- 模板实例化（{host} 替换 + lan 入口）；
- 预检超时回退（备选列表）与快捷搜索设置校验。
"""

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password

ADMIN = "admin"
ADMIN_PASS = "portal-p15"

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


def test_01_recycle_restore_purge(client: TestClient):
    """回收站：删除（软）→ 列表可见 → 恢复 → 再删 → purge 物理删除。"""
    app_id = client.post(
        "/api/apps", json={"name": "回收站测试"}, headers=_admin(client)
    ).json()["data"]["id"]
    client.delete(f"/api/apps/{app_id}", headers=_admin(client))
    rows = client.get("/api/apps/recycle-bin", headers=_admin(client)).json()["data"]
    assert any(r["id"] == app_id for r in rows)

    resp = client.post(f"/api/apps/{app_id}/restore", headers=_admin(client))
    assert resp.status_code == 200
    assert client.get(f"/api/apps/{app_id}", headers=_admin(client)).status_code == 200

    client.delete(f"/api/apps/{app_id}", headers=_admin(client))
    assert client.delete(f"/api/apps/{app_id}/purge", headers=_admin(client)).status_code == 200
    assert client.get(f"/api/apps/{app_id}", headers=_admin(client)).status_code == 404
    assert client.post(f"/api/apps/{app_id}/restore", headers=_admin(client)).status_code == 404


def test_02_template_instantiate(client: TestClient):
    """模板库：列表 + 一键实例化（{host} 替换 + lan 入口 + 标签）。"""
    resp = client.get("/api/apps/templates", headers=_admin(client))
    keys = [t["key"] for t in resp.json()["data"]]
    assert "qbittorrent" in keys and "jellyfin" in keys

    resp = client.post(
        "/api/apps/from-template",
        json={"key": "qbittorrent", "host": "192.168.1.50"},
        headers=_admin(client),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    app_id = data["id"]
    assert data["entry"] == "http://192.168.1.50:8080"

    app = client.get(f"/api/apps/{app_id}", headers=_admin(client)).json()["data"]
    assert app["name"] == "qBittorrent"
    assert app["health_target"] == "http://192.168.1.50:8080"
    assert json.loads(app["urls"] if isinstance(app["urls"], str) else "[]") or app.get("urls") is not None

    # 未知模板 404
    assert (
        client.post("/api/apps/from-template", json={"key": "nope", "host": "x"}, headers=_admin(client)).status_code
        == 404
    )
    # 清理（软删 → purge，避免软删残留干扰后续模块的 export round-trip 断言）
    client.delete(f"/api/apps/{app_id}", headers=_admin(client))
    client.delete(f"/api/apps/{app_id}/purge", headers=_admin(client))


def test_03_batch_ops(client: TestClient):
    """批量：停用/启用/移动分组/回收。"""
    ids = []
    for n in ("批量A", "批量B"):
        ids.append(client.post("/api/apps", json={"name": n}, headers=_admin(client)).json()["data"]["id"])
    resp = client.post("/api/apps/batch", json={"ids": ids, "op": "disable"}, headers=_admin(client))
    assert resp.json()["data"]["count"] == 2
    for i in ids:
        assert client.get(f"/api/apps/{i}", headers=_admin(client)).json()["data"]["enabled"] is False

    resp = client.post("/api/apps/batch", json={"ids": ids, "op": "enable"}, headers=_admin(client))
    assert resp.json()["data"]["count"] == 2
    client.post("/api/apps/batch", json={"ids": ids, "op": "recycle"}, headers=_admin(client))
    rows = client.get("/api/apps/recycle-bin", headers=_admin(client)).json()["data"]
    assert {r["id"] for r in rows} >= set(ids)
    for i in ids:
        client.delete(f"/api/apps/{i}/purge", headers=_admin(client))


def test_04_precheck_fallback_and_shortcuts(client: TestClient):
    """预检：死端口 → ok=False；无备选时 alternatives=[]；快捷搜索设置白名单校验。"""
    app_id = client.post(
        "/api/apps",
        json={"name": "预检目标", "health_type": "tcp", "health_target": "127.0.0.1:1"},
        headers=_admin(client),
    ).json()["data"]["id"]
    resp = client.post(f"/api/apps/{app_id}/precheck", headers=_admin(client))
    data = resp.json()["data"]
    assert data["ok"] is False and data["alternatives"] == []
    client.delete(f"/api/apps/{app_id}", headers=_admin(client))

    # 快捷搜索设置：合法保存 + 非法 422
    ok = client.put(
        "/api/settings",
        json={"values": {"home.search_shortcuts": [{"keyword": "gh", "url": "https://github.com/search?q={q}"}]}},
        headers=_admin(client),
    )
    assert ok.status_code == 200
    bad = client.put(
        "/api/settings",
        json={"values": {"home.search_shortcuts": [{"keyword": "gh"}]}},
        headers=_admin(client),
    )
    assert bad.status_code == 422
    client.put("/api/settings", json={"values": {"home.search_shortcuts": []}}, headers=_admin(client))


def test_05_widgets_summary(client: TestClient):
    """小组件聚合：形状校验（通知/Flow/容器字段）。"""
    resp = client.get("/api/widgets/summary", headers=_admin(client))
    data = resp.json()["data"]
    assert isinstance(data["notifications"], list)
    assert isinstance(data["flow_runs"], list)
    # docker 未启用 → None（前端隐藏）
    assert data["docker"] in (None, {"running": int, "stopped": int})

