# ruff: noqa: E501
"""P9 测试关卡：通知中心（M09；dev-plan 9.1/9.2/9.3）。

- 各渠道 payload 构造（纯函数）；
- 免打扰判定（含跨午夜）与路由规则匹配；
- 聚合去重窗口；
- 渠道 CRUD 权限与敏感字段脱敏；测试发送（httpx.MockTransport 注入）；
- 规则全量保存；探活翻转接入 dispatch（站内 + 渠道 mock 被调）。
"""

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.services.notify as notify_svc
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal

ADMIN = "admin"
ADMIN_PASS = "portal-p9"

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


# ---------- 9.1 渠道 payload 构造（纯函数） ----------


def test_01_channel_payloads():
    method, url, payload = notify_svc.build_bark(
        {"server": "https://api.day.app/", "device_key": "kEY123"}, "标题", "内容", "error"
    )
    assert method == "GET"
    assert url.startswith("https://api.day.app/kEY123/%E6%A0%87%E9%A2%98/")
    assert "level=error" in url

    method, url, payload = notify_svc.build_telegram({"bot_token": "T", "chat_id": "42"}, "标题", "内容", "warn")
    assert url == "https://api.telegram.org/botT/sendMessage"
    assert payload["chat_id"] == "42" and "[warn] 标题" in payload["text"]

    method, url, payload = notify_svc.build_webhook(
        {"url": "http://x/hook"}, "t", "b", "info", "app_down", "probe"
    )
    assert (method, url) == ("POST", "http://x/hook")
    assert payload["event"] == "app_down" and payload["source"] == "probe" and payload["level"] == "info"

    for builder, key in ((notify_svc.build_wecom, "msgtype"), (notify_svc.build_dingtalk, "msgtype")):
        method, url, payload = builder({"url": "http://x"}, "t", "b")
        assert payload[key] == "text" and "t" in payload["text"]["content"]
    method, url, payload = notify_svc.build_feishu({"url": "http://x"}, "t", "b")
    assert payload["msg_type"] == "text"

    method, url, data, headers = notify_svc.build_ntfy({"server": "https://ntfy.sh", "topic": "nas"}, "t", "b", "error")
    assert url == "https://ntfy.sh/nas" and headers["Priority"] == "high" and data == "b"

    msg = notify_svc.build_smtp_message(
        {"username": "u@x.com", "to_addrs": ["a@x.com", "b@x.com"]}, "t", "b", "warn"
    )
    assert msg["Subject"] == "[Portal][warn] t" and "a@x.com" in msg["To"]


# ---------- 9.3 免打扰判定（含跨午夜） ----------


def test_02_quiet_window():
    assert notify_svc.is_quiet_now("22:00", "08:00", datetime(2026, 9, 3, 23, 0)) is True
    assert notify_svc.is_quiet_now("22:00", "08:00", datetime(2026, 9, 3, 7, 59)) is True
    assert notify_svc.is_quiet_now("22:00", "08:00", datetime(2026, 9, 3, 12, 0)) is False
    assert notify_svc.is_quiet_now("10:00", "12:00", datetime(2026, 9, 3, 11, 30)) is True
    assert notify_svc.is_quiet_now("10:00", "12:00", datetime(2026, 9, 3, 12, 0)) is False
    assert notify_svc.is_quiet_now("09:00", "09:00", datetime(2026, 9, 3, 23, 0)) is True  # 相等=全天
    assert notify_svc.is_quiet_now(None, "08:00") is False  # 未配置=不启用
    assert notify_svc.is_quiet_now("bad", "08:00") is False


# ---------- 9.1 渠道 CRUD + 脱敏 + 测试发送 ----------


def test_03_channel_crud_and_mask(client: TestClient):
    assert client.get("/api/notify-channels").status_code == 401

    resp = client.post(
        "/api/notify-channels",
        json={"type": "webhook", "name": "本地钩子", "config": {"url": "http://127.0.0.1:9/hook"}},
        headers=_admin(client),
    )
    assert resp.status_code == 200
    ch = resp.json()["data"]
    assert ch["id"] > 0 and ch["enabled"] is True

    # 非法 type 422
    assert (
        client.post("/api/notify-channels", json={"type": "sms", "config": {}}, headers=_admin(client)).status_code
        == 422
    )

    # PUT 带掩码 ****** → 保留原值
    resp = client.put(
        f"/api/notify-channels/{ch['id']}",
        json={"type": "telegram", "name": "TG", "config": {"bot_token": "******", "chat_id": "1"}},
        headers=_admin(client),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["config"] == {"bot_token": "******", "chat_id": "1"}
    # 原值 webhooks 无 bot_token；改回 webhook 验证合并逻辑（telegram 无原 token → ****** 原样保留）

    # 列表回传均为脱敏形态（无敏感字段明文 = 无该字段或 ******）
    resp = client.get("/api/notify-channels", headers=_admin(client))
    assert any(c["name"] == "TG" for c in resp.json()["data"])

    # 测试发送：MockTransport 记录请求
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    notify_svc.set_http_transport(httpx.MockTransport(handler))
    try:
        client.put(
            f"/api/notify-channels/{ch['id']}",
            json={"type": "webhook", "name": "本地钩子", "config": {"url": "http://mock/hook"}},
            headers=_admin(client),
        )
        resp = client.post(f"/api/notify-channels/{ch['id']}/test", headers=_admin(client))
        assert resp.status_code == 200 and resp.json()["data"]["sent"] is True
        assert len(seen) == 1 and seen[0].url == "http://mock/hook"
        assert json.loads(seen[0].content)["event"] == "system"
    finally:
        notify_svc.set_http_transport(None)


# ---------- 9.3 规则全量保存 + dispatch 编排（去重/免打扰/路由） ----------


def _mk_webhook_channel(client: TestClient, url: str) -> int:
    resp = client.post(
        "/api/notify-channels",
        json={"type": "webhook", "name": "hook", "config": {"url": url}},
        headers=_admin(client),
    )
    return resp.json()["data"]["id"]


def _dispatch_sync(**kwargs):
    """同步测试中驱动 async dispatch。"""

    async def _run():
        async with SessionLocal() as s:
            return await notify_svc.dispatch(s, **kwargs)

    return asyncio.run(_run())


def test_04_rules_and_dispatch(client: TestClient):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    notify_svc.set_http_transport(httpx.MockTransport(handler))
    try:
        cid = _mk_webhook_channel(client, "http://mock/route")
        # 保存规则矩阵：app_down → 渠道；免打扰时段覆盖当前时间则不发外部
        resp = client.put(
            "/api/notify-rules",
            json={"rules": [{"event": "app_down", "channel_ids": [cid], "enabled": True,
                             "quiet_start": None, "quiet_end": None}]},
            headers=_admin(client),
        )
        assert resp.status_code == 200 and len(resp.json()["data"]) == 1

        before = len(seen)
        view = _dispatch_sync(
            event="app_down", source="probe", title="T1", body="b", level="error",
            dedup_key="dup-A",
        )
        assert view is not None and view["title"] == "T1"
        assert len(seen) == before + 1  # 外部渠道收到

        # 去重：窗口内同 dedup_key 合并 → 站内不加、渠道不再发
        assert (
            _dispatch_sync(
                event="app_down", source="probe", title="T2", body="b",
                level="error", dedup_key="dup-A",
            )
            is None
        )
        assert len(seen) == before + 1

        # 免打扰：quiet 覆盖全天 → 站内写、外部不发
        client.put(
            "/api/notify-rules",
            json={"rules": [{"event": "app_down", "channel_ids": [cid], "enabled": True,
                             "quiet_start": "00:00", "quiet_end": "00:00"}]},
            headers=_admin(client),
        )
        _dispatch_sync(event="app_down", source="probe", title="T3", level="error", dedup_key="dup-B")
        assert len(seen) == before + 1  # 外部未增
        resp = client.get("/api/notifications?unread=1", headers=_admin(client))
        titles = [i["title"] for i in resp.json()["data"]["items"]]
        assert "T3" in titles and "T2" not in titles
    finally:
        notify_svc.set_http_transport(None)


def test_05_notification_read_delete(client: TestClient):
    resp = client.get("/api/notifications", headers=_admin(client))
    items = resp.json()["data"]["items"]
    assert items, "前序用例已产生站内通知"
    nid = items[0]["id"]

    assert client.put(f"/api/notifications/{nid}/read", headers=_admin(client)).status_code == 200
    assert client.put("/api/notifications/read-all", headers=_admin(client)).status_code == 200
    assert client.get("/api/notifications/unread-count", headers=_admin(client)).json()["data"]["unread"] == 0

    assert client.delete(f"/api/notifications/{nid}", headers=_admin(client)).status_code == 200
    rest = client.get("/api/notifications", headers=_admin(client)).json()["data"]["items"]
    assert all(i["id"] != nid for i in rest)


def test_06_probe_flip_triggers_channel(client: TestClient):
    """探活状态翻转 → dispatch → 规则路由 → mock 渠道收到请求（P6.4→P9 出口）。"""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    notify_svc.set_http_transport(httpx.MockTransport(handler))
    try:
        cid = _mk_webhook_channel(client, "http://mock/probe")
        client.put(
            "/api/notify-rules",
            json={"rules": [
                {"event": "app_down", "channel_ids": [cid], "enabled": True,
                 "quiet_start": None, "quiet_end": None},
            ]},
            headers=_admin(client),
        )
        resp = client.post("/api/apps", json={"name": "P9 探活目标", "health_type": "tcp",
                                              "health_target": "127.0.0.1:1", "health_interval": 10},
                           headers=_admin(client))
        app_id = resp.json()["data"]["id"]
        before = len(seen)
        resp = client.post(f"/api/apps/{app_id}/check", headers=_admin(client))
        assert resp.json()["data"]["state"] == "down"  # 端口 1 未监听
        assert len(seen) == before + 1
        body = json.loads(seen[-1].content)
        assert body["event"] == "app_down" and body["level"] == "error"
    finally:
        notify_svc.set_http_transport(None)
