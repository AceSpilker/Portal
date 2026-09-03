"""P0 测试关卡：健康检查 + 建表与默认设置（dev-plan P0 单元测试）。

复用 conftest 的 session 级 client：自建 TestClient 退出时会触发 lifespan
shutdown，把全局调度器关掉，导致后续模块（如 test_p8_system）读到
scheduler_running=False。
"""

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings


def test_health_ok(client: TestClient):
    """统一响应结构 + 服务状态（api-spec §1/§2）。"""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["message"] == "ok"
    assert body["data"]["status"] == "ok"
    assert body["data"]["app"] == "portal"


def test_settings_table_ready_with_defaults():
    """P0.3：启动建表 + settings 默认键写入。"""
    db_file = Path(settings.data_dir) / "portal.db"
    assert db_file.is_file()


    conn = sqlite3.connect(db_file)
    try:
        rows = dict(conn.execute("SELECT key, value FROM settings").fetchall())
    finally:
        conn.close()
    assert "general.site_name" in rows
    assert "sync.enabled" in rows
