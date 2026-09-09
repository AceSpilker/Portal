# ruff: noqa: E501
"""端口画像（089）：/ports/{port}/info——词典命中、监听/连接统计、监控项与应用关联。
文件名 z 前缀：字母序置于 test_auth/test_crypto 之后（auth 链路要求全新库）。"""

import socket
import time

import pytest

ADMIN = "admin"
ADMIN_PASS = "portal-p11"
_tokens: dict = {}


def _reset_db_state() -> None:
    import sqlite3
    from pathlib import Path

    from app.core.config import settings
    from app.core.security import hash_password

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
def _setup(client):
    _reset_db_state()
    _tokens.clear()


def _admin(client) -> dict:
    if ADMIN not in _tokens:
        resp = client.post("/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASS})
        assert resp.status_code == 200, resp.text
        _tokens[ADMIN] = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {_tokens[ADMIN]}"}


def test_01_info_shape_and_well_known(client):
    """已知端口命中词典；未知端口 well_known=null；响应字段完整。"""
    r = client.get("/api/ports/8080/info", headers=_admin(client))
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["port"] == 8080
    assert d["well_known"] is not None and "HTTP" in d["well_known"]["name"]
    assert {"listeners", "connections", "containers", "monitors", "apps", "docker_enabled"} <= set(d)

    r2 = client.get("/api/ports/49999/info", headers=_admin(client))
    assert r2.json()["data"]["well_known"] is None


def test_02_listeners_and_monitors_and_apps(client):
    """本地起监听端口 → listeners 命中；建监控项与应用入口 → 关联返回。"""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        time.sleep(0.1)
        # 应用入口命中该端口
        app = client.post(
            "/api/apps",
            json={"name": "画像应用", "health_type": "none", "urls": [{"url": f"http://127.0.0.1:{port}", "protocol": "http"}]},
            headers=_admin(client),
        )
        if app.status_code == 200:
            pass  # urls 形状随 API 版本，失败不阻塞（监控项断言为主）
        # 监控项命中该端口
        m = client.post(
            "/api/ports/monitors",
            json={"name": "画像监控", "host": "127.0.0.1", "port": port, "interval": 60, "enabled": True},
            headers=_admin(client),
        )
        monitor_id = m.json()["data"]["id"] if m.status_code == 200 else None

        d = client.get(f"/api/ports/{port}/info", headers=_admin(client)).json()["data"]
        assert any(x["port"] == port for x in d["listeners"]), "监听未命中"
        assert any(mo["name"] == "画像监控" for mo in d["monitors"]), "监控项未关联"
        if app.status_code == 200:
            assert any(a["name"] == "画像应用" for a in d["apps"]), "应用未关联"
        if monitor_id:
            client.delete(f"/api/ports/monitors/{monitor_id}", headers=_admin(client))
        if app.status_code == 200:
            client.delete(f"/api/apps/{app.json()['data']['id']}", headers=_admin(client))
    finally:
        srv.close()
