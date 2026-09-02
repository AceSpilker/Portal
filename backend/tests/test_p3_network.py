"""P3 测试关卡：网络环境与智能解析（dev-plan P3 单元测试）。

沿用 P2 的测试基建（admin/alice 账号直改库重置，token 缓存解耦）。
覆盖 dev-plan P3 单测关卡：CIDR 匹配（命中/不命中/多档案顺序/无默认兜底/边界地址）、
环境档案 CRUD 与约束；detect/resolve/me-env/矩阵在后续用例段补充。
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password
from app.services.network import ip_matches, match_profile

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


# ============ CIDR 匹配服务（M04-8 单测关卡）============


class _FakeProfile:
    """match_profile 单测用的轻量档案对象（免建库）。"""

    def __init__(self, id_, name, match_type="cidr", cidrs=None, enabled=True, sort=0):
        self.id = id_
        self.name = name
        self.match_type = match_type
        self.cidrs = cidrs or []
        self.enabled = enabled
        self.sort = sort


def test_01_cidr_hit_and_miss():
    assert ip_matches("192.168.1.10", ["192.168.1.0/24"])
    assert not ip_matches("10.0.0.5", ["192.168.1.0/24"])
    assert not ip_matches("not-an-ip", ["192.168.1.0/24"])
    assert not ip_matches("192.168.1.10", ["bad-cidr"])


def test_02_cidr_boundary_addresses():
    # 网络地址与广播地址均视为命中（边界含端点）
    assert ip_matches("192.168.1.0", ["192.168.1.0/24"])
    assert ip_matches("192.168.1.255", ["192.168.1.0/24"])
    assert not ip_matches("192.168.2.0", ["192.168.1.0/24"])
    # IPv6
    assert ip_matches("fd00::1234", ["fd00::/8"])
    assert not ip_matches("192.168.1.1", ["fd00::/8"])


def test_03_multi_profile_order():
    """IP 命中多档案时按 sort 顺序取先者；sort 相同按 id。"""
    p_late = _FakeProfile(1, "公司", cidrs=["10.0.0.0/8"], sort=5)
    p_first = _FakeProfile(2, "家庭", cidrs=["10.0.0.0/8"], sort=1)
    p_id = _FakeProfile(3, "id小者优先", cidrs=["10.0.0.0/8"], sort=1)
    assert match_profile("10.1.2.3", [p_late, p_first]).name == "家庭"
    assert match_profile("10.1.2.3", [p_late, p_id]).name == "id小者优先"


def test_04_default_fallback():
    """未命中任何 cidr 档案走默认兜底；无默认档案返回 None；停用档案不参与。"""
    default = _FakeProfile(9, "外部兜底", match_type="default")
    home = _FakeProfile(1, "家庭", cidrs=["192.168.1.0/24"])
    assert match_profile("8.8.8.8", [home, default]) is default
    assert match_profile("8.8.8.8", [home]) is None
    assert match_profile("192.168.1.7", [home, default]) is home
    disabled = _FakeProfile(2, "停用", cidrs=["8.8.8.0/24"], enabled=False)
    assert match_profile("8.8.8.8", [disabled, default]) is default


# ============ 环境档案 CRUD（M04-7）============


def test_05_read_requires_auth(client: TestClient):
    assert client.get("/api/network-profiles").status_code == 401


def test_06_write_requires_admin(client: TestClient):
    resp = client.post(
        "/api/network-profiles",
        json={"name": "x", "cidrs": ["10.0.0.0/8"]},
        headers=_alice(client),
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 3001
    assert client.get("/api/network-profiles", headers=_alice(client)).status_code == 200


def test_07_create_cidr_profiles(client: TestClient):
    resp = client.post(
        "/api/network-profiles",
        json={"name": "家庭内网", "cidrs": ["192.168.1.0/24"], "prefer_types": ["lan", "domain"]},
        headers=_admin(client),
    )
    assert resp.status_code == 200, resp.text
    _ids["home"] = resp.json()["data"]["id"]
    assert resp.json()["data"]["is_default"] is False

    resp = client.post(
        "/api/network-profiles",
        json={"name": "公司网络", "cidrs": ["10.0.0.0/8"], "prefer_types": ["domain"]},
        headers=_admin(client),
    )
    assert resp.status_code == 200, resp.text
    _ids["office"] = resp.json()["data"]["id"]

    data = client.get("/api/network-profiles", headers=_alice(client)).json()["data"]
    assert [p["name"] for p in data] == ["家庭内网", "公司网络"]


def test_08_cidr_validation(client: TestClient):
    # cidr 档案缺网段
    resp = client.post(
        "/api/network-profiles", json={"name": "坏档案", "cidrs": []}, headers=_admin(client)
    )
    assert resp.status_code == 422
    # 非法网段格式
    resp = client.post(
        "/api/network-profiles",
        json={"name": "坏档案", "cidrs": ["300.1.2.3/24"]},
        headers=_admin(client),
    )
    assert resp.status_code == 422
    assert "CIDR" in resp.json()["message"]


def test_09_default_profile_unique(client: TestClient):
    resp = client.post(
        "/api/network-profiles",
        json={"name": "外部兜底", "match_type": "default"},
        headers=_admin(client),
    )
    assert resp.status_code == 200, resp.text
    _ids["default"] = resp.json()["data"]["id"]
    assert resp.json()["data"]["cidrs"] == []
    # 第二个 default 档案被拒
    resp = client.post(
        "/api/network-profiles",
        json={"name": "另一个兜底", "match_type": "default"},
        headers=_admin(client),
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == 4002
    # 把已有 cidr 档案改成 default 也被拒
    resp = client.put(
        f"/api/network-profiles/{_ids['office']}",
        json={"match_type": "default"},
        headers=_admin(client),
    )
    assert resp.status_code == 409


def test_10_update_profile(client: TestClient):
    pid = _ids["office"]
    resp = client.put(
        f"/api/network-profiles/{pid}",
        json={"name": "公司网络 v2", "cidrs": ["10.0.0.0/8", "172.16.0.0/12"], "sort": -1},
        headers=_admin(client),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["name"] == "公司网络 v2"
    assert data["cidrs"] == ["10.0.0.0/8", "172.16.0.0/12"]
    assert data["sort"] == -1


def test_11_delete_profile(client: TestClient):
    resp = client.post(
        "/api/network-profiles",
        json={"name": "待删除", "cidrs": ["10.9.0.0/16"]},
        headers=_admin(client),
    )
    pid = resp.json()["data"]["id"]
    assert client.delete(f"/api/network-profiles/{pid}", headers=_admin(client)).status_code == 200
    assert client.delete(f"/api/network-profiles/{pid}", headers=_admin(client)).status_code == 404
    # 普通用户不可删
    resp = client.delete(
        f"/api/network-profiles/{_ids['home']}", headers=_alice(client)
    )
    assert resp.status_code == 403


# ============ 环境探测（M04-8；P3.2）============


def test_12_detect_requires_auth(client: TestClient):
    assert client.post("/api/network-profiles/detect").status_code == 401


def test_13_detect_by_source_ip(client: TestClient):
    """用 X-Forwarded-For 模拟不同来源 IP（反代场景约定）。"""
    # 命中家庭内网档案
    resp = client.post(
        "/api/network-profiles/detect",
        headers=_alice(client) | {"X-Forwarded-For": "192.168.1.55"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["client_ip"] == "192.168.1.55"
    assert data["matched_profile"]["name"] == "家庭内网"
    # 命中公司网段（10.0.0.0/8 或 172.16.0.0/12）
    resp = client.post(
        "/api/network-profiles/detect",
        headers=_alice(client) | {"X-Real-IP": "10.3.4.5"},
    )
    assert resp.json()["data"]["matched_profile"]["name"] == "公司网络 v2"
    # 未命中走默认兜底档案
    resp = client.post(
        "/api/network-profiles/detect",
        headers=_alice(client) | {"X-Forwarded-For": "8.8.8.8"},
    )
    data = resp.json()["data"]
    assert data["matched_profile"]["name"] == "外部兜底"
    # candidates 为启用档案全集（按优先序）
    assert [c["name"] for c in data["candidates"]] == ["公司网络 v2", "家庭内网", "外部兜底"]


# ============ 智能解析（M04-10；P3.3）============


def _make_app(client: TestClient, name: str, urls: list[dict]) -> int:
    resp = client.post("/api/apps", json={"name": name}, headers=_admin(client))
    assert resp.status_code == 200, resp.text
    app_id = resp.json()["data"]["id"]
    for u in urls:
        resp = client.post(f"/api/apps/{app_id}/urls", json=u, headers=_admin(client))
        assert resp.status_code == 200, resp.text
    return app_id


def test_14_resolve_requires_auth(client: TestClient):
    app_id = _make_app(
        client,
        "Jellyfin",
        [
            {"access_type": "domain", "url": "https://jf.example.com"},
            {"access_type": "lan", "url": "http://192.168.1.10:8096"},
        ],
    )
    _ids["jellyfin"] = app_id
    assert client.get(f"/api/apps/{app_id}/resolve").status_code == 401


def test_15_resolve_by_env_priority(client: TestClient):
    app_id = _ids["jellyfin"]
    # 家庭内网（prefer lan>domain）：内网 IP 来源 → 推荐 lan 入口
    resp = client.get(
        f"/api/apps/{app_id}/resolve",
        headers=_alice(client) | {"X-Forwarded-For": "192.168.1.55"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["recommended"]["access_type"] == "lan"
    assert [a["access_type"] for a in data["alternatives"]] == ["domain"]
    # 外部来源（默认兜底档案 prefer=[]）→ 维持 sort 原序，domain 在前
    resp = client.get(
        f"/api/apps/{app_id}/resolve",
        headers=_alice(client) | {"X-Forwarded-For": "8.8.8.8"},
    )
    data = resp.json()["data"]
    assert data["recommended"]["access_type"] == "domain"
    assert [a["access_type"] for a in data["alternatives"]] == ["lan"]


def test_16_resolve_explicit_env_param(client: TestClient):
    app_id = _ids["jellyfin"]
    # 显式指定公司档案 pid（prefer domain）
    pid = _ids["office"]
    resp = client.get(f"/api/apps/{app_id}/resolve?env={pid}", headers=_alice(client))
    assert resp.json()["data"]["recommended"]["access_type"] == "domain"
    # 非法 env 参数
    resp = client.get(f"/api/apps/{app_id}/resolve?env=abc", headers=_alice(client))
    assert resp.status_code == 422
    # 不存在的档案
    resp = client.get(f"/api/apps/{app_id}/resolve?env=99999", headers=_alice(client))
    assert resp.status_code == 404


def test_17_resolve_app_not_found_and_no_urls(client: TestClient):
    assert client.get("/api/apps/99999/resolve", headers=_alice(client)).status_code == 404
    app_id = _make_app(client, "无入口应用", [])
    resp = client.get(f"/api/apps/{app_id}/resolve", headers=_alice(client))
    assert resp.status_code == 200
    assert resp.json()["data"] == {"recommended": None, "alternatives": []}


def test_18_resolve_manual_overrides_auto(client: TestClient):
    """手动偏好 > 自动识别（M04-9）：家庭内网来源但手动选公司档案 → 推荐 domain。"""
    app_id = _ids["jellyfin"]
    db_file = Path(settings.data_dir) / "portal.db"
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            "UPDATE users SET prefs = ? WHERE username = ?",
            (f'{{"env_profile_id": {_ids["office"]}}}', "alice"),
        )
        conn.commit()
    finally:
        conn.close()
    resp = client.get(
        f"/api/apps/{app_id}/resolve",
        headers=_alice(client) | {"X-Forwarded-For": "192.168.1.55"},
    )
    assert resp.json()["data"]["recommended"]["access_type"] == "domain"
    # 手动偏好的档案被删后回退自动识别
    resp = client.post(
        "/api/network-profiles",
        json={"name": "临时偏好", "cidrs": ["10.10.0.0/16"]},
        headers=_admin(client),
    )
    temp_pid = resp.json()["data"]["id"]
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            "UPDATE users SET prefs = ? WHERE username = ?",
            (f'{{"env_profile_id": {temp_pid}}}', "alice"),
        )
        conn.commit()
    finally:
        conn.close()
    client.delete(f"/api/network-profiles/{temp_pid}", headers=_admin(client))
    resp = client.get(
        f"/api/apps/{app_id}/resolve",
        headers=_alice(client) | {"X-Forwarded-For": "192.168.1.55"},
    )
    assert resp.json()["data"]["recommended"]["access_type"] == "lan"


# ============ 手动环境偏好（M04-9；P3.4）============


def test_19_me_env_requires_auth(client: TestClient):
    assert client.put("/api/me/env", json={"profile_id": None}).status_code == 401


def test_20_me_env_roundtrip(client: TestClient):
    """设置 → 生效 → 清除，选择被记忆（M04-9）。"""
    home_pid = _ids["home"]
    # GET：初始无手动偏好
    resp = client.get("/api/me/env", headers=_alice(client) | {"X-Forwarded-For": "8.8.8.8"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["manual_profile"] is None
    # 设置手动偏好为家庭档案
    resp = client.put(
        "/api/me/env",
        json={"profile_id": home_pid},
        headers=_alice(client) | {"X-Forwarded-For": "8.8.8.8"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["manual_profile"]["id"] == home_pid
    assert data["auto_profile"]["name"] == "外部兜底"
    assert data["effective_profile"]["id"] == home_pid
    # GET：手动偏好被记忆（选择持久化，刷新/换设备仍在）
    resp = client.get("/api/me/env", headers=_alice(client) | {"X-Forwarded-For": "8.8.8.8"})
    assert resp.json()["data"]["manual_profile"]["id"] == home_pid
    # resolve 在外部来源下也应使用手动偏好（家庭 → lan 优先）
    resp = client.get(
        f"/api/apps/{_ids['jellyfin']}/resolve",
        headers=_alice(client) | {"X-Forwarded-For": "8.8.8.8"},
    )
    assert resp.json()["data"]["recommended"]["access_type"] == "lan"
    # 清除手动偏好 → 回到自动
    resp = client.put(
        "/api/me/env", json={"profile_id": None}, headers=_alice(client)
    )
    data = resp.json()["data"]
    assert data["manual_profile"] is None
    assert data["effective_profile"]["name"] == "外部兜底"
    # 不存在的档案
    resp = client.put("/api/me/env", json={"profile_id": 99999}, headers=_alice(client))
    assert resp.status_code == 404


# ============ 连通性测试矩阵（M04-13；P3.6）============


def _free_tcp_port() -> int:
    """借一个空闲 TCP 端口：先绑定获取端口号再释放（矩阵测试用作断开端口）。"""
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_21_matrix_requires_admin(client: TestClient):
    assert client.get("/api/connectivity/matrix", headers=_alice(client)).status_code == 403
    assert client.get("/api/connectivity/matrix").status_code == 401


def test_22_matrix_states_and_structure(client: TestClient):
    """起本地 TCP 监听模拟 up；closed 端口 → down；乱串 → unknown。"""
    import socket
    import threading

    # 常驻 TCP 监听线程（模块内多个断言共用）
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    open_port = listener.getsockname()[1]

    def _serve():
        listener.settimeout(10)
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            conn.close()

    threading.Thread(target=_serve, daemon=True).start()
    closed_port = _free_tcp_port()

    app_id = _make_app(
        client,
        "矩阵测试应用",
        [
            {"access_type": "lan", "url": f"http://127.0.0.1:{open_port}"},
            {"access_type": "domain", "url": f"http://127.0.0.1:{closed_port}"},
            {"access_type": "custom", "url": "host:99999"},
        ],
    )
    _ids["matrix_app"] = app_id

    resp = client.get("/api/connectivity/matrix", headers=_admin(client))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert "probed_at" in data
    row = next(a for a in data["apps"] if a["id"] == app_id)
    by_type = {u["access_type"]: u for u in row["urls"]}
    assert by_type["lan"]["state"] == "up"
    assert isinstance(by_type["lan"]["latency_ms"], int)
    assert by_type["domain"]["state"] == "down"
    assert by_type["domain"]["latency_ms"] is None
    # 无法解析 host:port 的入口 → unknown
    assert by_type["custom"]["state"] == "unknown"
    listener.close()
