# ruff: noqa: E501
"""P13 测试关卡：AI 助手（M05；dev-plan 13.1~13.5）。

- Prompt 组装（意图导航清单 + NAS 摘要开关）；
- navigate 协议解析（含格式错误兜底）；
- 会话截断策略（上下文轮数）；
- Provider CRUD 掩码；chat WS（MockTransport 假上游流）。
"""

import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.services.ai as ai_svc
from app.core.config import settings
from app.core.security import hash_password

ADMIN = "admin"
ADMIN_PASS = "portal-p13"

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


def test_01_prompt_and_navigate():
    """Prompt 组装含应用清单与 NAS 摘要开关；navigate 协议解析含兜底。"""
    from types import SimpleNamespace

    apps = [
        SimpleNamespace(id=3, name="下载器", description="qBittorrent 下载"),
        SimpleNamespace(id=5, name="Jellyfin", description=""),
    ]
    prompt_off = ai_svc.build_system_prompt(apps, context_aware=False, stats=None)
    assert "3|下载器" in prompt_off and 'action":"navigate"' in prompt_off
    assert "NAS 状态摘要" not in prompt_off

    prompt_on = ai_svc.build_system_prompt(
        apps, context_aware=True, stats={"cpu": 42, "mem": 60, "disk": 55, "containers": 2}
    )
    assert "NAS 状态摘要" in prompt_on and "CPU 42%" in prompt_on

    # navigate 解析
    assert ai_svc.parse_navigate('{"action":"navigate","app_id":3}') == 3
    assert ai_svc.parse_navigate('{"action":"navigate","app_id":3}\n帮你打开了。') == 3
    assert ai_svc.parse_navigate('{"action":"jump","app_id":3}') is None  # action 不符
    assert ai_svc.parse_navigate('{"action":"navigate","app_id":"3"}') is None  # 非整数
    assert ai_svc.parse_navigate("{broken json") is None  # 坏 JSON
    assert ai_svc.parse_navigate("普通回答，无协议") is None
    assert ai_svc.parse_navigate("") is None


def test_02_trim_history():
    """上下文轮数截断：只保留最近 N 轮 user/assistant 对。"""
    from app.models.ai import AiMessage

    msgs = []
    for i in range(5):
        msgs.append(AiMessage(conversation_id=1, role="user", content=f"u{i}"))
        msgs.append(AiMessage(conversation_id=1, role="assistant", content=f"a{i}"))
    assert len(ai_svc.trim_history(msgs, 2)) == 4  # 2 轮 = 4 条
    pairs = ai_svc.trim_history(msgs, 2)
    assert pairs[0][1] == "u3" and pairs[-1][1] == "a4"
    assert ai_svc.trim_history(msgs, 0) == []
    assert len(ai_svc.trim_history(msgs, 10)) == 10


def test_03_provider_crud_and_mask(client: TestClient):
    """Provider CRUD：key 掩码回传、保存 ****** 保持原值；测试端点走 mock。"""
    resp = client.post(
        "/api/ai/providers",
        json={"name": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
              "api_key": "sk-real-key", "model": "deepseek-chat"},
        headers=_admin(client),
    )
    assert resp.status_code == 200
    pid = resp.json()["data"]["id"]
    assert resp.json()["data"]["api_key"] == "******"

    rows = client.get("/api/ai/providers", headers=_admin(client)).json()["data"]
    assert rows[0]["api_key"] == "******"

    # PUT 掩码保持原值
    client.put(
        f"/api/ai/providers/{pid}",
        json={"name": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
              "api_key": "******", "model": "deepseek-reasoner"},
        headers=_admin(client),
    )
    # 测试端点（Mock 上游返回模型列表）
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]})

    real_transport = ai_svc._http_transport if hasattr(ai_svc, "_http_transport") else None
    import app.services.ai as svc

    svc.set_http_transport = getattr(svc, "set_http_transport", None)
    # ai.test_provider 直接用 httpx.AsyncClient——用 monkeypatch 方式注入 transport
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        original_init(self, *a, **kw)

    httpx.AsyncClient.__init__ = patched_init
    try:
        resp = client.post(
            "/api/ai/providers/test",
            json={"base_url": "https://api.deepseek.com/v1", "api_key": "sk-real-key"},
            headers=_admin(client),
        )
        assert resp.json()["data"]["ok"] is True
        assert "deepseek-chat" in resp.json()["data"]["models"]
    finally:
        httpx.AsyncClient.__init__ = original_init
        if real_transport is not None:
            ai_svc.set_http_transport(real_transport)


def test_04_chat_ws_stream_and_navigate(client: TestClient):
    """chat WS：假上游流式输出 + navigate 协议回帧 + 消息落库。"""
    # 配置 provider 指向假上游
    client.post(
        "/api/ai/providers",
        json={"name": "Mock", "base_url": "http://mockai/v1", "api_key": "k", "model": "m1"},
        headers=_admin(client),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        body = json.loads(request.content)
        system = next(m for m in body["messages"] if m["role"] == "system")
        assert "navigate" in system["content"]  # 意图导航清单已注入
        lines = [
            'data: {"choices":[{"delta":{"content":"{\\"action\\":\\"navigate\\",\\"app_id\\":3}"}}]}',
            "data: [DONE]",
        ]
        return httpx.Response(200, text="\n\n".join(lines))

    def patched_init(self, *a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        original_async(self, *a, **kw)

    original_async = httpx.AsyncClient.__init__
    httpx.AsyncClient.__init__ = patched_init
    try:
        conv = client.post(
            "/api/ai/conversations", json={"title": "新对话"}, headers=_admin(client)
        ).json()["data"]
        cid = conv["id"]
        token = _tokens[ADMIN]

        with client.websocket_connect(f"/ws/ai-chat?token={token}") as ws:
            ws.send_json({"conversation_id": cid, "content": "帮我打开下载器"})
            frames = []
            while True:
                frame = ws.receive_json()
                frames.append(frame)
                if frame.get("type") in ("done", "error"):
                    break
        done = frames[-1]
        assert done["type"] == "done"
        assert done["navigate_app_id"] == 3
        assert frames[0]["type"] == "delta"

        # 消息落库
        msgs = client.get(f"/api/ai/conversations/{cid}/messages", headers=_admin(client)).json()["data"]
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert "帮我打开下载器" in msgs[0]["content"]
    finally:
        httpx.AsyncClient.__init__ = original_async

    client.delete(f"/api/ai/conversations/{cid}", headers=_admin(client))


def test_05_app_draft_generation(client: TestClient):
    """AI 生成应用草稿：JSON 提取（容忍 ```json 包裹）+ 非法输出 502。"""
    draft_text = '```json\n{"name":"Jellyfin","description":"媒体服务器","health_type":"http","health_target":"http://192.168.1.10:8096","tags":["媒体"]}\n```'

    def handler(request: httpx.Request) -> httpx.Response:
        lines = [
            f'data: {json.dumps({"choices": [{"delta": {"content": part}}]})}'
            for part in (draft_text[:20], draft_text[20:])
        ]
        lines.append("data: [DONE]")
        return httpx.Response(200, text="\n\n".join(lines))

    original_async = httpx.AsyncClient.__init__

    def patched_init(self, *a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        original_async(self, *a, **kw)

    httpx.AsyncClient.__init__ = patched_init
    try:
        resp = client.post(
            "/api/ai/generate/app-draft",
            json={"description": "这是一个跑在 8096 端口的媒体服务器 Jellyfin，网页可以直接访问"},
            headers=_admin(client),
        )
        draft = resp.json()["data"]
        assert draft["name"] == "Jellyfin" and draft["health_type"] == "http"
        assert draft["tags"] == ["媒体"]
    finally:
        httpx.AsyncClient.__init__ = original_async

    # 解析兜底：坏 JSON → 502
    def bad_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"我不会"}}]}\n\ndata: [DONE]')

    def bad_init(self, *a, **kw):
        kw["transport"] = httpx.MockTransport(bad_handler)
        original_async(self, *a, **kw)

    httpx.AsyncClient.__init__ = bad_init
    try:
        resp = client.post(
            "/api/ai/generate/app-draft",
            json={"description": "随便一段无法解析的描述内容"},
            headers=_admin(client),
        )
        assert resp.status_code == 502
    finally:
        httpx.AsyncClient.__init__ = original_async
