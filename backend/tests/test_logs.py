"""日志中心测试关卡（072）：全站写操作审计中间件 + system_logs 查询 API + Handler 入队。

自举沿用套件既有解耦模式（sqlite3 直改库重置 admin 密码，见 test_icons），
不依赖 test_auth 先行执行。
"""

import logging
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.log_handler import SystemLogHandler
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.system_log import SystemLog

ADMIN_USER = "admin"
ADMIN_PASS = "portal-logs"

_TOKEN_CACHE: dict = {}


def _reset_admin() -> None:
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
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="module", autouse=True)
def _setup(client: TestClient):
    _reset_admin()
    _TOKEN_CACHE.clear()


@pytest.fixture(autouse=True)
def _disable_login_lock(monkeypatch):
    """本文件不测限流：关闭登录锁检查，避免其他文件遗留的失败计数自锁。"""
    import app.api.v1.auth as auth_mod

    async def _never_locked(_ip: str) -> bool:
        return False

    monkeypatch.setattr(auth_mod, "is_locked", _never_locked)


def _login(client: TestClient) -> str:
    if "token" not in _TOKEN_CACHE:
        resp = client.post(
            "/api/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}
        ).json()["data"]
        _TOKEN_CACHE["token"] = resp["access_token"]
    return _TOKEN_CACHE["token"]


@pytest.fixture(autouse=True)
def _disable_login_lock(monkeypatch):
    """本文件不测限流：关闭登录锁检查，避免其他文件遗留的失败计数自锁。"""
    import app.api.v1.auth as auth_mod

    async def _never_locked(_ip: str) -> bool:
        return False

    monkeypatch.setattr(auth_mod, "is_locked", _never_locked)


def _wait_audit(client: TestClient, action: str, timeout: float = 3.0) -> dict | None:
    """审计中间件异步落库，轮询等待该动作出现。"""
    deadline = time.time() + timeout
    token = _login(client)
    while time.time() < deadline:
        resp = client.get(
            f"/api/audit-logs?action={action}&range=all&page_size=200",
            headers={"Authorization": f"Bearer {token}"},
        ).json()["data"]
        for item in resp["items"]:
            if item["action"] == action:
                return item
        time.sleep(0.1)
    return None


def test_01_write_operation_auto_audited(client):
    """认证后的写操作自动落审计（含状态码与耗时），action 形如 POST /api/apps。"""
    token = _login(client)
    resp = client.post(
        "/api/apps",
        json={"name": "audit-probe", "urls": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    app_id = resp.json()["data"]["id"]
    row = _wait_audit(client, "POST /api/apps")
    assert row is not None, "写操作未落审计"
    assert "status=200" in row["detail"] and "ms" in row["detail"]
    # 清理探针应用
    client.delete(
        f"/api/apps/{app_id}", headers={"Authorization": f"Bearer {token}"}
    )


def test_02_get_never_audited(client):
    """GET 只读请求不产生审计记录。"""
    hdrs = {"Authorization": f"Bearer {_login(client)}"}

    def _total() -> int:
        resp = client.get("/api/audit-logs?range=all&page_size=200", headers=hdrs)
        return resp.json()["data"]["total"]

    before = _total()
    client.get("/api/apps", headers=hdrs)
    time.sleep(0.3)
    assert _total() == before


def test_03_login_not_duplicated(client):
    """登录已由 auth 手写业务审计（action=login），中间件不再记一条 POST /api/auth/login。"""
    client.post("/api/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
    time.sleep(0.3)
    resp = client.get(
        "/api/audit-logs?action=POST /api/auth/login&range=all",
        headers={"Authorization": f"Bearer {_login(client)}"},
    ).json()["data"]
    assert resp["total"] == 0


def test_04_audit_action_prefix_filter(client):
    """action 筛选按前缀匹配：action=login 命中 login 系列记录。"""
    resp = client.get(
        "/api/audit-logs?action=login&range=all&page_size=200",
        headers={"Authorization": f"Bearer {_login(client)}"},
    ).json()["data"]
    assert resp["total"] >= 1
    assert all(item["action"].startswith("login") for item in resp["items"])


def test_05_system_logs_query_and_filter(client):
    """system_logs 分页查询 + level 筛选 + 关键词。"""
    import asyncio

    async def _seed():
        async with SessionLocal() as session:
            session.add_all(
                [
                    SystemLog(
                        level="ERROR", logger="uvicorn.error", message="boom-test 认证异常堆栈"
                    ),
                    SystemLog(
                        level="WARNING", logger="apscheduler.executors", message="job raised 警告"
                    ),
                    SystemLog(level="INFO", logger="app", message="startup ok"),
                ]
            )
            await session.commit()

    asyncio.run(_seed())
    token = _login(client)
    resp = client.get(
        "/api/system-logs?level=ERROR&range=all&q=boom-test",
        headers={"Authorization": f"Bearer {token}"},
    ).json()["data"]
    assert resp["total"] >= 1
    assert all(item["level"] == "ERROR" for item in resp["items"])
    assert all("boom-test" in item["message"] for item in resp["items"])

    # 非 admin 不可见
    resp2 = client.get("/api/system-logs")
    assert resp2.status_code == 401


def test_06_handler_enqueues_warning_only():
    """Handler：WARNING+ 入队；普通 INFO 丢弃；启动类 INFO 放行；异常静默。"""
    import queue

    handler = SystemLogHandler()
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    q: queue.Queue = handler.__dict__.get("_Queue__put", None) or None  # noqa: F841 防误读
    from app.core import log_handler

    before = log_handler._QUEUE.qsize()

    rec = logging.LogRecord("app.test", logging.WARNING, __file__, 1, "warn-x", None, None)
    handler.emit(rec)
    assert log_handler._QUEUE.qsize() == before + 1

    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "GET / 200", None, None)
    handler.emit(rec)
    assert log_handler._QUEUE.qsize() == before + 1  # 普通 INFO 不入库

    rec = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        __file__,
        1,
        "Uvicorn running on http://0.0.0.0:8000",
        None,
        None,
    )
    handler.emit(rec)
    assert log_handler._QUEUE.qsize() == before + 2  # 启动类 INFO 放行

    rec = logging.LogRecord("app.test", logging.INFO, __file__, 1, "x" * 5000, None, None)
    handler.emit(rec)  # 超 2000 截断且不入库（INFO）——不抛错即通过
