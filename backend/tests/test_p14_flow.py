# ruff: noqa: E501
"""P14 测试关卡：Flow 自动化表单版（M06；dev-plan 14.1~14.5）。

- 表达式沙箱（禁调用/导入/未知名称）；变量插值；
- 状态机：条件不满足跳过后续；HTTP 失败重试；失败落 runs + flow_failed 通知；
- webhook token 鉴权与吊销（旧 token 失效）；cron 表达式注册。
"""

import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.services.flow_svc as flow_svc
from app.core.config import settings
from app.core.security import hash_password

ADMIN = "admin"
ADMIN_PASS = "portal-p14"

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


def test_01_sandbox_and_interpolate():
    """表达式沙箱：白名单语法可用；调用/导入/未知名称拒绝。"""
    assert flow_svc.safe_eval("prev.status_code == 200", {"prev": {"status_code": 200}}) is True
    assert flow_svc.safe_eval("prev.n > 1 and prev.n < 5", {"prev": {"n": 3}}) is True
    assert flow_svc.safe_eval('vars["k"] == "v"', {"vars": {"k": "v"}}) is True
    assert flow_svc.safe_eval("1 + 2 * 3 == 7", {}) is True

    for bad in (
        "__import__('os')",
        "open('/etc/passwd')",
        "eval('1')",
        "(lambda: 1)()",
        "nonexistent_var == 1",
        "[x for x in prev]",
    ):
        try:
            flow_svc.safe_eval(bad, {"prev": {}})
            raise AssertionError(f"should reject: {bad}")
        except flow_svc.UnsafeExpression:
            pass

    # 插值
    assert flow_svc.interpolate("状态 {prev.status_code}，{vars.name}", {"prev": {"status_code": 200}, "vars": {"name": "OK"}}) == "状态 200，OK"
    assert flow_svc.interpolate("保持 {unknown} 原样", {}) == "保持 {unknown} 原样"


def test_02_flow_crud_and_condition_skip(client: TestClient):
    """条件不满足 → 后续动作跳过（dry-run 可见 skipped）。"""
    resp = client.post(
        "/api/flows",
        json={
            "name": "条件跳过测试",
            "trigger_type": "manual",
            "actions": [
                {"type": "condition", "expression": "prev.status_code == 200"},
                {"type": "notify", "config": {"title": "不应发送"}},
            ],
        },
        headers=_admin(client),
    )
    fid = resp.json()["data"]["id"]
    resp = client.post(f"/api/flows/{fid}/dry-run", headers=_admin(client))
    steps = resp.json()["data"]["steps"]
    assert steps[0]["result"] is False
    assert steps[1].get("skipped") is True
    client.delete(f"/api/flows/{fid}", headers=_admin(client))


def test_03_http_retry_and_failure_notify(client: TestClient):
    """HTTP 失败重试（retry=2）→ failed 落 runs + flow_failed 站内通知。"""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(500)  # 持续失败，验证重试与失败告警

    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        original_init(self, *a, **kw)

    # 用不可达端口构造失败；重试间隔压到最小
    resp = client.post(
        "/api/flows",
        json={
            "name": "重试失败测试",
            "trigger_type": "manual",
            "actions": [{"type": "http", "config": {"method": "GET", "url": "http://127.0.0.1:9/nope"}}],
            "retry": 2,
            "retry_interval": 5,
        },
        headers=_admin(client),
    )
    fid = resp.json()["data"]["id"]
    httpx.AsyncClient.__init__ = patched_init
    try:
        resp = client.post(f"/api/flows/{fid}/run", headers=_admin(client))
        assert resp.json()["data"]["status"] == "failed"
    finally:
        httpx.AsyncClient.__init__ = original_init

    runs = client.get(f"/api/flows/{fid}/runs", headers=_admin(client)).json()["data"]
    assert runs[0]["status"] == "failed"
    steps = runs[0]["steps"]
    assert sum(1 for s in steps if s.get("attempt")) == 2  # 两次重试记录
    assert len(seen) == 3  # 首次 + 2 次重试

    resp = client.get("/api/notifications", headers=_admin(client))
    titles = [i["title"] for i in resp.json()["data"]["items"]]
    assert any("重试失败测试」执行失败" in t for t in titles)
    client.delete(f"/api/flows/{fid}", headers=_admin(client))


def test_04_webhook_token_and_revoke(client: TestClient):
    """webhook 触发：token 有效触发成功；重置后旧 token 失效。"""
    resp = client.post(
        "/api/flows",
        json={
            "name": "Hook 测试",
            "trigger_type": "webhook",
            "trigger_config": {},
            "actions": [{"type": "notify", "config": {"title": "hook 触发 {payload.kind}", "body": ""}}],
            "enabled": True,
        },
        headers=_admin(client),
    )
    fid = resp.json()["data"]["id"]
    token1 = resp.json()["data"]["webhook_token"]
    assert token1

    # hooks 免加密豁免：明文 POST 可触发（无 Authorization）
    resp = client.post(f"/api/hooks/flow/{token1}", json={"payload": {"kind": "test"}})
    assert resp.status_code == 200 and resp.json()["data"]["status"] == "success"

    # 无效 token 404
    assert client.post("/api/hooks/flow/bad-token", json={}).status_code == 404

    # 重置 token → 旧 token 失效
    new_token = client.post(f"/api/flows/{fid}/reset-token", headers=_admin(client)).json()["data"]["webhook_token"]
    assert new_token != token1
    assert client.post(f"/api/hooks/flow/{token1}", json={}).status_code == 404
    assert client.post(f"/api/hooks/flow/{new_token}", json={}).status_code == 200
    client.delete(f"/api/flows/{fid}", headers=_admin(client))


def test_05_webhook_full_chain_to_channel(client: TestClient):
    """业务关卡全链路：webhook 触发 → 通知动作（变量插值）→ 站内通知。"""
    resp = client.post(
        "/api/flows",
        json={
            "name": "下载完成通知",
            "trigger_type": "webhook",
            "actions": [
                {"type": "notify", "config": {"title": "下载完成：{payload.kind}", "body": "来自 webhook"}},
            ],
            "enabled": True,
        },
        headers=_admin(client),
    )
    token = resp.json()["data"]["webhook_token"]
    client.post(f"/api/hooks/flow/{token}", json={"payload": {"kind": "qBittorrent"}})
    resp = client.get("/api/notifications", headers=_admin(client))
    titles = [i["title"] for i in resp.json()["data"]["items"]]
    assert any(t == "下载完成：qBittorrent" for t in titles)
    rows = client.get("/api/flows", headers=_admin(client)).json()["data"]
    for r in rows:
        if r["name"] == "下载完成通知":
            client.delete(f"/api/flows/{r['id']}", headers=_admin(client))
