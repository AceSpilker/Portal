"""SPA 深链接回退回归（065 实测：StaticFiles(html=True) 对 /login 等前端路由直接 404，
开发态由 Vite 回退掩盖，仅生产托管形态暴露）。前端 dist 未构建时相关用例跳过。"""

from pathlib import Path

import pytest

_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html"


@pytest.mark.skipif(not _DIST.exists(), reason="frontend/dist 未构建")
def test_01_spa_deep_link_serves_index(client):
    """深链接 /login 直接访问返回 index.html（200 HTML）。"""
    resp = client.get("/login", headers={"accept": "text/html,application/xhtml+xml"})
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert b"<html" in resp.content.lower()


@pytest.mark.skipif(not _DIST.exists(), reason="frontend/dist 未构建")
def test_02_spa_deep_link_refresh_on_any_route(client):
    """任意前端路由（如 /monitor）刷新同样回退 index.html。"""
    resp = client.get("/monitor", headers={"accept": "text/html"})
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


@pytest.mark.skipif(not _DIST.exists(), reason="frontend/dist 未构建")
def test_03_api_unknown_path_still_404_json(client):
    """未知 API 路径不回退 HTML，保持 404 JSON。"""
    resp = client.get("/api/nonexistent", headers={"accept": "text/html"})
    assert resp.status_code == 404
    assert "application/json" in resp.headers["content-type"]
