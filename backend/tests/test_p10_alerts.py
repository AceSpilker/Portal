# ruff: noqa: E501
"""P10 测试关卡：阈值告警状态机（M17-14/15）、可用率计算（M07-3/4）、证书解析（M07-6）。

- 触发/恢复状态机：越限持续 N 分钟才触发、冷却窗口、恢复通知；
- 可用率：窗口起点状态推断 + down 段累计；
- 证书：notAfter 解析与到期分级；
- 端点权限与形状：alerts rules CRUD/test/events、processes/docker-stats/certs。
"""

import asyncio
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.services.alerts as alerts_svc
from app.core.config import settings
from app.core.security import hash_password

ADMIN = "admin"
ADMIN_PASS = "portal-p10"

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
    alerts_svc._STATE.clear()


def _admin(client: TestClient) -> dict:
    if ADMIN not in _tokens:
        resp = client.post("/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASS})
        assert resp.status_code == 200, resp.text
        _tokens[ADMIN] = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {_tokens[ADMIN]}"}


def _evaluate_sync():
    from app.db.session import SessionLocal

    async def _run():
        async with SessionLocal() as s:
            await alerts_svc.evaluate_alerts(s)

    asyncio.run(_run())


def test_01_alert_state_machine(client: TestClient):
    """越限持续 duration 后触发一次；冷却内不重复；恢复发 info。"""
    resp = client.post(
        "/api/alerts/rules",
        json={"name": "CPU过高", "metric": "cpu", "op": ">", "threshold": -1, "duration_min": 1,
              "level": "warn", "enabled": True},
        headers=_admin(client),
    )
    assert resp.status_code == 200
    rule_id = resp.json()["data"]["id"]

    # 第一次评估：创建 since，不触发
    _evaluate_sync()
    st = alerts_svc._STATE.get(rule_id)
    assert st is not None and st["firing"] is False

    # 手动推进越限起点 2 分钟 → 触发（source=metric 站内通知）
    alerts_svc._STATE[rule_id]["since"] = time.time() - 120
    _evaluate_sync()
    assert alerts_svc._STATE[rule_id]["firing"] is True
    resp = client.get("/api/alerts/events?range=24h", headers=_admin(client))
    fired = [e for e in resp.json()["data"] if "CPU过高" in e["title"]]
    assert fired and fired[0]["level"] == "warn"

    # 冷却窗口内重复评估 → 不再新增
    alerts_svc._STATE[rule_id]["since"] = time.time() - 3600
    alerts_svc._STATE[rule_id]["firing"] = False  # 模拟 last_fired 刚写完的再次评估
    _evaluate_sync()
    resp = client.get("/api/alerts/events?range=24h", headers=_admin(client))
    assert len([e for e in resp.json()["data"] if "CPU过高" in e["title"]]) == 1

    # 恢复：阈值不可能越限（cpu > 1000）→ 恢复路径发 info 通知
    client.put(
        f"/api/alerts/rules/{rule_id}",
        json={"name": "CPU过高", "metric": "cpu", "op": ">", "threshold": 1000, "duration_min": 1,
              "level": "warn", "enabled": True},
        headers=_admin(client),
    )
    # PUT 会清状态重新计时；手动恢复 firing 态模拟「告警中 → 恢复」的真实序列
    alerts_svc._STATE[rule_id] = {"since": time.time() - 120, "firing": True}
    _evaluate_sync()
    resp = client.get("/api/alerts/events?range=24h", headers=_admin(client))
    assert any("已恢复" in e["title"] for e in resp.json()["data"])

    client.delete(f"/api/alerts/rules/{rule_id}", headers=_admin(client))
    assert alerts_svc._STATE.get(rule_id) is None


def test_02_availability_calc(client: TestClient):
    """24h 窗口：down 段 1h → 可用率 ≈ 95.83%。"""
    resp = client.post("/api/apps", json={"name": "可用性目标", "health_type": "tcp",
                                          "health_target": "127.0.0.1:1"}, headers=_admin(client))
    app_id = resp.json()["data"]["id"]
    # 造状态与事件：起点 up，1h 前 down 至今
    now = datetime.utcnow()
    db_file = Path(settings.data_dir) / "portal.db"
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO app_status (app_id, state, latency_ms, checked_at, since, message)"
            " VALUES (?, 'down', 5, ?, ?, '')",
            (app_id, now, now - timedelta(hours=1)),
        )
        conn.execute(
            "INSERT INTO probe_events (app_id, event, latency_ms, created_at) VALUES (?, 'down', 5, ?)",
            (app_id, now - timedelta(hours=1)),
        )
        conn.commit()
    finally:
        conn.close()
    resp = client.get("/api/probe/availability?range=24h", headers=_admin(client))
    assert resp.status_code == 200
    row = next(a for a in resp.json()["data"]["apps"] if a["app_id"] == app_id)
    assert abs(row["uptime_pct"] - 95.83) < 0.1
    assert row["current_state"] == "down"
    assert len(resp.json()["data"]["timeline"]) >= 1
    client.delete(f"/api/apps/{app_id}", headers=_admin(client))


def test_03_cert_parse_and_levels():
    assert alerts_svc.parse_not_after("Sep  1 12:00:00 2027 GMT") == datetime(2027, 9, 1, 12, 0)
    assert alerts_svc.parse_not_after(None) is None
    # 分级
    def level_for(days: float) -> str:
        not_after = datetime.utcnow() + timedelta(days=days)
        raw = not_after.strftime("%b %d %H:%M:%S %Y GMT")
        parsed = alerts_svc.parse_not_after(raw)
        days_left = (parsed - datetime.utcnow()).total_seconds() / 86400
        if days_left <= 1:
            return "error"
        if days_left <= 7:
            return "warn"
        if days_left <= 30:
            return "info"
        return "ok"

    assert level_for(0.5) == "error"
    assert level_for(5) == "warn"
    assert level_for(20) == "info"
    assert level_for(90) == "ok"


def test_04_rule_api_permission_and_validation(client: TestClient):
    assert client.get("/api/alerts/rules").status_code == 401
    assert (
        client.post("/api/alerts/rules", json={"metric": "bogus", "threshold": 1}, headers=_admin(client)).status_code
        == 422
    )
    # test 端点：当前值存在且 violated 布尔
    resp = client.post(
        "/api/alerts/rules",
        json={"name": "CPU测试", "metric": "cpu", "op": ">", "threshold": -1, "duration_min": 1},
        headers=_admin(client),
    )
    rid = resp.json()["data"]["id"]
    resp = client.post(f"/api/alerts/rules/{rid}/test", headers=_admin(client))
    data = resp.json()["data"]
    assert isinstance(data["current"], (int, float)) and data["violated"] is True
    client.delete(f"/api/alerts/rules/{rid}", headers=_admin(client))


def test_05_process_docker_certs_endpoints(client: TestClient):
    resp = client.get("/api/monitor/processes?sort=cpu&limit=5", headers=_admin(client))
    assert resp.status_code == 200 and len(resp.json()["data"]) <= 5
    row = resp.json()["data"][0]
    assert {"pid", "name", "cpu_percent", "mem_percent"} <= set(row)

    resp = client.get("/api/monitor/docker-stats", headers=_admin(client))
    assert resp.status_code == 200 and isinstance(resp.json()["data"], list)

    resp = client.get("/api/monitor/certs", headers=_admin(client))
    assert resp.status_code == 200 and resp.json()["data"] == []

    # hosts 白名单校验 + 保存
    resp = client.put("/api/monitor/certs/hosts", json={"hosts": ["github.com"]}, headers=_admin(client))
    assert resp.json()["data"] == ["github.com"]
    resp = client.put(
        "/api/monitor/certs/hosts",
        json={"hosts": ["x" * 300]},
        headers=_admin(client),
    )
    assert resp.status_code == 422
    # 清理
    client.put("/api/monitor/certs/hosts", json={"hosts": []}, headers=_admin(client))
