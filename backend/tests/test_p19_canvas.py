# ruff: noqa: E501
"""P19 测试关卡：Flow 画布编排（M06-3/11~14/19；dev-plan 19.1~19.3）。

- 互转：表单线性 ⇄ 画布图 round-trip；图校验（环/未知类型/缺开始节点）；
- 画布执行：条件 true/false 路由、fan-out 分支并行、分支失败传播；
- 进阶节点：延时/变量（真实）、SSH/Docker/AI（mock）；
- 模板一键创建、导出/导入 round-trip。
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password

ADMIN = "admin"
ADMIN_PASS = "portal-p19"

_tokens: dict = {}


def _reset_db_state() -> None:
    import sqlite3

    db_file = Path(settings.data_dir) / "portal.db"
    conn = sqlite3.connect(db_file)
    try:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (ADMIN,)).fetchone():
            conn.execute(
                "UPDATE users SET password_hash = ?, is_active = 1, totp_enabled = 0 WHERE username = ?",
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


def test_01_linear_graph_interconversion():
    """互转（19.1）：线性→图→线性 round-trip；条件走 true 边；start 节点不入动作。"""
    from app.services.flow_svc import graph_to_linear, linear_to_graph

    actions = [
        {"type": "http", "name": "查询", "config": {"method": "GET", "url": "http://x"}},
        {"type": "condition", "name": "成功？", "expression": "prev.status_code == 200", "config": {}},
        {"type": "notify", "name": "通知", "config": {"title": "完成"}},
    ]
    graph = linear_to_graph(actions)
    ids = [n["id"] for n in graph["nodes"]]
    assert ids[0] == "start" and len(graph["nodes"]) == 4
    cond_out = [e for e in graph["edges"] if e["source"] == "n2"]
    assert cond_out[0]["source_handle"] == "true"
    back = graph_to_linear(graph)
    assert back == actions
    # graph_to_linear 对未知/空图安全
    assert graph_to_linear({"nodes": [], "edges": []}) == []


def test_02_graph_validation(client: TestClient):
    """图校验（19.1）：环拒绝 / 未知类型拒绝 / 缺开始节点拒绝 / 合法图通过。"""
    h = _admin(client)
    cyclic = {
        "nodes": [
            {"id": "start", "type": "trigger", "name": "开始", "config": {}},
            {"id": "a", "type": "delay", "name": "d", "config": {"seconds": 1}},
        ],
        "edges": [
            {"source": "start", "target": "a"},
            {"source": "a", "target": "a"},
        ],
    }
    resp = client.post("/api/flows", json={
        "name": "环图", "trigger_type": "manual", "actions": [], "graph": cyclic,
    }, headers=h)
    assert resp.status_code == 422 and "环" in resp.json()["message"]
    bad_type = {
        "nodes": [
            {"id": "start", "type": "trigger", "name": "开始", "config": {}},
            {"id": "a", "type": "nuclear", "name": "x", "config": {}},
        ],
        "edges": [{"source": "start", "target": "a"}],
    }
    assert client.post("/api/flows", json={"name": "坏类型", "graph": bad_type, "actions": []}, headers=h).status_code == 422
    no_trigger = {
        "nodes": [{"id": "a", "type": "delay", "name": "d", "config": {"seconds": 1}}],
        "edges": [],
    }
    assert client.post("/api/flows", json={"name": "无开始", "graph": no_trigger, "actions": []}, headers=h).status_code == 422
    ok_graph = {
        "nodes": [
            {"id": "start", "type": "trigger", "name": "开始", "config": {}},
            {"id": "a", "type": "variable", "name": "设变量", "config": {"name": "city", "value": "杭州"}},
        ],
        "edges": [{"source": "start", "target": "a"}],
    }
    ok = client.post("/api/flows", json={"name": "合法画布", "graph": ok_graph, "actions": []}, headers=h)
    assert ok.status_code == 200, ok.text
    view = ok.json()["data"]
    assert view["graph"]["nodes"][0]["id"] == "start"
    assert [a["type"] for a in view["actions"]] == ["variable"]  # 投影不含 trigger
    fid = view["id"]
    client.delete(f"/api/flows/{fid}", headers=h)


def test_03_canvas_condition_routing(client: TestClient):
    """画布执行（19.1）：条件 true/false 路由各自支线；false 无边则成功终止。"""
    h = _admin(client)
    graph = {
        "nodes": [
            {"id": "start", "type": "trigger", "name": "开始", "config": {}},
            {"id": "c", "type": "condition", "name": "恒真",
             "expression": "1 == 1", "config": {}},
            {"id": "t", "type": "variable", "name": "真分支",
             "config": {"name": "branch", "value": "true-branch"}},
            {"id": "f", "type": "variable", "name": "假分支",
             "config": {"name": "branch", "value": "false-branch"}},
            {"id": "n", "type": "notify", "name": "汇总",
             "config": {"title": "分支={vars.branch}", "body": "x"}},
        ],
        "edges": [
            {"source": "start", "target": "c"},
            {"source": "c", "target": "t", "source_handle": "true"},
            {"source": "c", "target": "f", "source_handle": "false"},
            {"source": "t", "target": "n"},
            {"source": "f", "target": "n"},
        ],
    }
    fid = client.post("/api/flows", json={
        "name": "条件路由", "graph": graph, "actions": [], "trigger_type": "manual",
    }, headers=h).json()["data"]["id"]
    run = client.post(f"/api/flows/{fid}/run", headers=h).json()["data"]
    assert run["status"] == "success"
    detail = client.get(f"/api/flow-runs/{run['run_id']}", headers=h).json()["data"]
    log = detail["steps"]
    branch_logs = [e for e in log if e.get("name") == "真分支"]
    assert branch_logs, "应走 true 分支"
    assert not any(e.get("name") == "假分支" for e in log)
    client.delete(f"/api/flows/{fid}", headers=h)


def test_04_canvas_fanout_parallel(client: TestClient):
    """分支并行（19.1）：fan-out 两条支线都执行（支线独立副本、互不串变量）。"""
    h = _admin(client)
    graph = {
        "nodes": [
            {"id": "start", "type": "trigger", "name": "开始", "config": {}},
            {"id": "a", "type": "variable", "name": "支线A", "config": {"name": "va", "value": "A"}},
            {"id": "b", "type": "variable", "name": "支线B", "config": {"name": "vb", "value": "B"}},
        ],
        "edges": [
            {"source": "start", "target": "a"},
            {"source": "start", "target": "b"},
        ],
    }
    fid = client.post("/api/flows", json={"name": "并行", "graph": graph, "actions": []}, headers=h).json()["data"]["id"]
    run = client.post(f"/api/flows/{fid}/run", headers=h).json()["data"]
    assert run["status"] == "success"
    detail = client.get(f"/api/flow-runs/{run['run_id']}", headers=h).json()["data"]
    names = [e.get("name") for e in detail["steps"]]
    assert names.count("支线A") == 1 and names.count("支线B") == 1
    client.delete(f"/api/flows/{fid}", headers=h)


def test_05_delay_variable_nodes(client: TestClient):
    """延时/变量节点（19.2）：变量插值向下游传递；延时真实等待并记录。"""
    h = _admin(client)
    graph = {
        "nodes": [
            {"id": "start", "type": "trigger", "name": "开始", "config": {}},
            {"id": "v", "type": "variable", "name": "设值", "config": {"name": "who", "value": "P19"}},
            {"id": "d", "type": "delay", "name": "等 1 秒", "config": {"seconds": 1}},
            {"id": "n", "type": "notify", "name": "通知", "config": {"title": "你好 {vars.who}", "body": "d"}},
        ],
        "edges": [
            {"source": "start", "target": "v"},
            {"source": "v", "target": "d"},
            {"source": "d", "target": "n"},
        ],
    }
    fid = client.post("/api/flows", json={"name": "延时变量", "graph": graph, "actions": []}, headers=h).json()["data"]["id"]
    run = client.post(f"/api/flows/{fid}/run", headers=h).json()["data"]
    assert run["status"] == "success"
    detail = client.get(f"/api/flow-runs/{run['run_id']}", headers=h).json()["data"]
    assert detail["duration_ms"] >= 900
    log = detail["steps"]
    delay_log = next(e for e in log if e.get("name") == "等 1 秒")
    assert delay_log["delay_seconds"] == 1
    client.delete(f"/api/flows/{fid}", headers=h)


def test_06_ssh_docker_ai_nodes(client: TestClient, monkeypatch):
    """进阶节点（19.2）：SSH/Docker/AI 执行器（mock 上游）。"""
    # SSH：mock asyncssh.connect
    class FakeResult:
        exit_status = 0
        stdout = "ok from ssh"

    class FakeConn:
        async def run(self, cmd):
            assert cmd == "uptime"
            return FakeResult()

    class FakeConnect:
        """模拟 asyncssh.connect 返回值：可 await 且支持 async with。"""

        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, *a):
            return False

        def __await__(self):
            async def _c():
                return FakeConn()
            return _c().__await__()

    import asyncio
    import sys
    import types

    from app.services import flow_svc

    real_module = sys.modules.get("asyncssh")
    sys.modules["asyncssh"] = types.SimpleNamespace(
        connect=lambda *a, **k: FakeConnect(), Error=Exception,
    )


    async def _main():
        try:
            out = await flow_svc._run_ssh_action(
                {"host": "127.0.0.1", "username": "root", "password": "x", "command": "uptime"},
                {},
            )
            assert out["exit_code"] == 0 and "ok from ssh" in out["output"]
        finally:
            if real_module is not None:
                sys.modules["asyncssh"] = real_module

        # Docker：monkeypatch container_op
        from app.services import docker_svc

        async def fake_op(name, op):
            return {"name": name, "op": op}
        monkeypatch.setattr(docker_svc, "container_op", fake_op)
        out2 = await flow_svc._run_docker_action({"container": "Redis", "op": "restart"}, {})
        assert out2["ok"] is True and out2["container"] == "Redis"

        # AI：monkeypatch active_provider + httpx post（chat/completions 非流式）
        class FakeResp:
            status_code = 200

            def json(self):
                return {"choices": [{"message": {"content": "一切正常"}}]}

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **k):
                return FakeResp()

        import httpx as _httpx

        monkeypatch.setattr(_httpx, "AsyncClient", FakeClient)

        from app.services import ai as ai_mod

        async def fake_provider(session):
            return {"base_url": "http://mock", "api_key": "k", "model": "m"}
        monkeypatch.setattr(ai_mod, "active_provider", fake_provider)
        out3 = await flow_svc._run_ai_action(None, {"prompt": "检查"}, {"prev": {"status_code": 200}})
        assert "一切正常" in out3["reply"]

    asyncio.run(_main())


def test_07_templates_and_import_export(client: TestClient):
    """模板与分享（19.3）：模板清单/一键创建（含画布）/导出/导入 round-trip。"""
    h = _admin(client)
    tpls = client.get("/api/flows/templates", headers=h).json()["data"]
    keys = {t["key"] for t in tpls}
    assert {"offline-restart", "download-digest", "http-watchdog"} <= keys
    created = client.post("/api/flows/from-template", json={"key": "offline-restart"}, headers=h)
    assert created.status_code == 200, created.text
    view = created.json()["data"]
    assert view["graph"]["nodes"] and view["trigger_type"] == "event"
    assert view["enabled"] is False  # 模板创建默认停用
    # 导出
    exp = client.get(f"/api/flows/{view['id']}/export", headers=h).json()["data"]
    assert exp["name"] and "webhook_token" not in exp and "id" not in exp
    # 删除后导入还原
    client.delete(f"/api/flows/{view['id']}", headers=h)
    imp = client.post("/api/flows/import", json=exp, headers=h)
    assert imp.status_code == 200, imp.text
    re_view = imp.json()["data"]
    assert re_view["name"] == exp["name"] and re_view["graph"]["nodes"]
    # 非法导入 422
    bad = client.post("/api/flows/import", json={}, headers=h)
    assert bad.status_code == 422
    client.delete(f"/api/flows/{re_view['id']}", headers=h)
