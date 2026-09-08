"""法定节假日测试关卡（077）：聚合纯函数 + DB 缓存路径 + 端点权限/数据。

自举沿用套件解耦模式（sqlite3 直改库重置 admin 密码，见 test_icons/test_logs）。
"""

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.setting import Setting
from app.services import holidays as holidays_svc

ADMIN_USER = "admin"
ADMIN_PASS = "portal-holidays"

_SAMPLE_DAYS = [
    {"name": "元旦", "date": "2026-01-01", "isOffDay": True},
    {"name": "元旦", "date": "2026-01-02", "isOffDay": True},
    {"name": "元旦", "date": "2026-01-03", "isOffDay": True},
    {"name": "元旦", "date": "2026-01-04", "isOffDay": False},
    {"name": "春节", "date": "2026-02-15", "isOffDay": True},
    {"name": "春节", "date": "2026-02-16", "isOffDay": True},
    {"name": "春节", "date": "2026-02-28", "isOffDay": False},
]

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


def test_01_summarize_groups_and_ranges():
    """聚合：按节日名归组、相邻休息日合并区间、调休日单列。"""
    summary = holidays_svc.summarize(_SAMPLE_DAYS)
    by_name = {s["name"]: s for s in summary}
    yuandan = by_name["元旦"]
    assert yuandan["rest_days"] == 3
    assert yuandan["rest_ranges"] == [
        {"start": "2026-01-01", "end": "2026-01-03", "days": 3}
    ]
    assert yuandan["makeup_dates"] == ["2026-01-04"]
    chunjie = by_name["春节"]
    assert chunjie["rest_days"] == 2
    assert chunjie["makeup_dates"] == ["2026-02-28"]


def test_02_endpoint_reads_db_cache_without_network(client, monkeypatch):
    """端点优先读 Setting 年度缓存；无网络也可用（_fetch 被替换即失败可见）。"""
    import asyncio

    async def _seed():
        async with SessionLocal() as session:
            await session.merge(
                Setting(
                    key="calendar.holidays_2026",
                    value=json.dumps(
                        {"year": 2026, "days": _SAMPLE_DAYS, "fetched_at": "2026-01-01T00:00:00Z"}
                    ),
                )
            )
            await session.commit()

    asyncio.run(_seed())

    async def _boom(year: int) -> dict | None:
        raise AssertionError("不应发起外网抓取")

    monkeypatch.setattr(holidays_svc, "_fetch", _boom)
    resp = client.get(
        "/api/calendar/holidays?year=2026",
        headers={"Authorization": f"Bearer {_login(client)}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["year"] == 2026 and len(data["days"]) == len(_SAMPLE_DAYS)
    summary = {s["name"]: s for s in data["summary"]}
    assert summary["元旦"]["rest_days"] == 3


def test_03_unauthenticated_rejected(client):
    assert client.get("/api/calendar/holidays?year=2026").status_code == 401
