# ruff: noqa: E501
"""天气城市设置（085）：home.weather_city 读写 + /widgets/weather 城市参数与代理分支。

httpx 外呼用 monkeypatch AsyncClient.__init__ 注入 MockTransport（test_p13 同款手法），
捕获实际请求 URL 验证：设置值生效 / query 参数优先 / 中文百分号编码 / 上游失败返回 null。
"""

import httpx
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
    yield
    # 清理天气城市，避免影响其他用例
    client.put("/api/settings", json={"values": {"home.weather_city": ""}},
               headers=_admin(client))


def _admin(client) -> dict:
    if ADMIN not in _tokens:
        resp = client.post("/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASS})
        assert resp.status_code == 200, resp.text
        _tokens[ADMIN] = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {_tokens[ADMIN]}"}


_J1 = {
    "current_condition": [{
        "temp_C": "31", "FeelsLikeC": "33", "humidity": "60",
        "weatherDesc": [{"value": "Sunny"}],
    }],
    "nearest_area": [{"areaName": [{"value": "Beijing"}]}],
    # 端点取 hourly[4]（wttr.in J1 实际为 8 个三小时时段），测试数据需 ≥5 条
    "weather": [{"date": "2026-09-09", "maxtempC": "32", "mintempC": "21",
                 "hourly": [{"weatherDesc": [{"value": v}]} for v in
                            ("Clear", "Sunny", "Sunny", "Partly cloudy", "Sunny")]}],
}


def test_01_city_setting_and_query_param(client, monkeypatch):
    """设置值生效且中文编码；query 参数优先于设置；响应形状完整。"""
    resp = client.put("/api/settings", json={"values": {"home.weather_city": "北京"}},
                      headers=_admin(client))
    assert resp.status_code == 200

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=_J1)

    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        original_init(self, *a, **kw)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    # 无参数 → 读设置「北京」，URL 百分号编码
    resp = client.get("/api/widgets/weather", headers=_admin(client))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data, f"resp={resp.text} seen={seen}"
    # 090 起城市显示优先用户配置名（填中文显示中文），描述回退英文
    assert data["city"] == "北京" and data["temp_c"] == 31 and len(data["days"]) == 1
    assert "%E5%8C%97%E4%BA%AC" in seen[-1]

    # query 参数优先于设置
    client.get("/api/widgets/weather", params={"city": "Shanghai"}, headers=_admin(client))
    assert "Shanghai" in seen[-1] and "%E5%8C%97%E4%BA%AC" not in seen[-1]


def test_02_upstream_failure_returns_null(client, monkeypatch):
    """上游异常 → data=null（前端隐藏组件，不报 500）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        original_init(self, *a, **kw)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)
    resp = client.get("/api/widgets/weather", params={"city": "Nowhere"}, headers=_admin(client))
    assert resp.status_code == 200 and resp.json()["data"] is None


def test_03_setting_validation(client):
    """>60 字符城市名 422；空串可写（恢复自动定位）。"""
    bad = client.put("/api/settings",
                     json={"values": {"home.weather_city": "城" * 61}},
                     headers=_admin(client))
    assert bad.status_code == 422
    ok = client.put("/api/settings", json={"values": {"home.weather_city": ""}},
                    headers=_admin(client))
    assert ok.status_code == 200
