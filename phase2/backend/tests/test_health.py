"""D0.4/D0.2 关卡：健康检查 + ADP 信封形态 + 校验错误 2001。"""

import httpx


async def test_01_health_public_and_shape(asgi_client: httpx.Client):
    resp = await asgi_client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    # ADP 原生信封：code=200 / msg / data（迁移方案 §5.1）
    assert body["code"] == 200
    assert body["msg"] == "ok"
    data = body["data"]
    assert data["status"] == "ok"
    assert data["app"] == "portal"
    assert isinstance(data["initialized"], bool)


async def test_02_unknown_api_returns_json_404(asgi_client: httpx.Client):
    resp = await asgi_client.get("/api/definitely-not-a-route")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


async def test_03_validation_error_2001(asgi_client: httpx.Client):
    # /api/crypto/handshake 缺字段 → Ninja 校验失败 → 2001 + 可读中文文案
    resp = await asgi_client.post("/api/crypto/handshake", json={})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == 2001
    assert "参数校验失败" in body["msg"]
    assert "必填" in body["msg"]


async def test_04_validation_error_english_by_accept_language(asgi_client: httpx.Client):
    resp = await asgi_client.post(
        "/api/crypto/handshake",
        json={},
        headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    body = resp.json()
    assert body["code"] == 2001
    assert "Validation failed" in body["msg"]
    assert "required" in body["msg"]


async def test_05_probe_echo_plain_when_encryption_off(asgi_client: httpx.Client):
    resp = await asgi_client.post("/api/_probe/echo", json={"echo": "hello"})
    assert resp.status_code == 200
    assert resp.json() == {"code": 200, "msg": "ok", "data": {"echo": "hello"}}
