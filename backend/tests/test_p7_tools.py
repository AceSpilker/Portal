# ruff: noqa: E501
"""P7.3 测试关卡：WoL 魔术包构造（dev-plan 单元测试关卡明确要求）/ 端口测试 / 目标 CRUD。"""

import socket
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password

ADMIN = "admin"
ADMIN_PASS = "portal-p2"

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
    if "admin" not in _tokens:
        resp = client.post("/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASS})
        assert resp.status_code == 200, resp.text
        _tokens["admin"] = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {_tokens['admin']}"}


def test_01_magic_packet_construction():
    """魔术包：6×FF 前缀 + MAC 重复 16 次 = 102 字节；分隔符与大小写规范化。"""
    from app.services.tools import build_magic_packet

    pk = build_magic_packet("AA:BB:CC:DD:EE:FF")
    assert len(pk) == 102
    assert pk[:6] == b"\xff" * 6
    assert pk[6:12] == bytes.fromhex("AABBCCDDEEFF")
    assert pk[-6:] == bytes.fromhex("AABBCCDDEEFF")
    # 连字符/小写等价
    assert build_magic_packet("aa-bb-cc-dd-ee-ff") == pk


def test_02_magic_packet_invalid():
    import pytest as _pytest

    from app.services.tools import build_magic_packet

    for bad in ("", "AA:BB", "ZZ:BB:CC:DD:EE:FF", "AA:BB:CC:DD:EE:FF:00"):
        with _pytest.raises(ValueError):
            build_magic_packet(bad)


def test_03_check_tcp_port():
    """端口测试：监听端口 ok=True 且延迟非负；关闭端口 ok=False。"""
    from app.services.tools import check_tcp_port

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        r = check_tcp_port("127.0.0.1", port)
        assert r["ok"] is True and r["latency_ms"] >= 0
    finally:
        s.close()
    dead = _free_port()
    assert check_tcp_port("127.0.0.1", dead)["ok"] is False


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_04_tools_endpoints_permission_and_flow(client: TestClient):
    """工具端点：未认证 401；WoL 合法/非法 MAC；port-check；目标 CRUD。"""
    assert client.post("/api/tools/wol", json={"mac": "AA:BB:CC:DD:EE:FF"}).status_code == 401
    assert client.post("/api/tools/port-check", json={"host": "127.0.0.1", "port": 80}).status_code == 401

    # 非法 MAC → 422
    resp = client.post("/api/tools/wol", json={"mac": "bad"}, headers=_admin(client))
    assert resp.status_code == 422

    # 合法广播发送（本机回环广播允许；送达与否不影响发送成功）
    resp = client.post("/api/tools/wol", json={"mac": "AA:BB:CC:DD:EE:FF"}, headers=_admin(client))
    assert resp.status_code == 200
    assert resp.json()["data"]["sent_bytes"] == 102

    # port-check：监听端口 up
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        resp = client.post(
            "/api/tools/port-check",
            json={"host": "127.0.0.1", "port": port},
            headers=_admin(client),
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["ok"] is True
    finally:
        s.close()

    # 目标 CRUD
    resp = client.post(
        "/api/tools/wol-targets",
        json={"name": "NAS", "mac": "AA:BB:CC:DD:EE:FF", "note": "测试"},
        headers=_admin(client),
    )
    assert resp.status_code == 200
    tid = resp.json()["data"]["id"]
    resp = client.get("/api/tools/wol-targets", headers=_admin(client))
    assert any(t["name"] == "NAS" for t in resp.json()["data"])
    assert client.delete(f"/api/tools/wol-targets/{tid}", headers=_admin(client)).status_code == 200
    assert client.get("/api/tools/wol-targets", headers=_admin(client)).json()["data"] == []
