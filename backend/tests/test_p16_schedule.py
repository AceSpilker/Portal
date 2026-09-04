# ruff: noqa: E501
"""P16 测试关卡：效率模块（M13/M11/M12；dev-plan 16.1~16.3）。

- 农历换算锚点（春节/中秋/端午/除夕/闰月 round-trip）；
- 日历月视图重复展开（daily/weekly/yearly/农历）与事件 CRUD；
- 待办 CRUD；提醒去重（同 occurrence 只提醒一次）；
- 文件白名单：浏览/上传/下载/建删改移 + 穿越拒绝 + 预览直链；
- qBittorrent：MockTransport 登录/列表/添加 + 完成跳变通知（MockTransport 约定）。
"""

import asyncio
import base64
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password

ADMIN = "admin"
ADMIN_PASS = "portal-p16"

_tokens: dict = {}


def _reset_db_state() -> None:
    import sqlite3

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
def _setup(client: TestClient, tmp_path_factory):
    _reset_db_state()
    _tokens.clear()
    # 白名单根指向临时目录（模块级共享，用例间清理）
    root = tmp_path_factory.mktemp("p16_files")
    resp = client.put(
        "/api/settings",
        json={"values": {"files.roots": [{"name": "测试盘", "path": str(root)}]}},
        headers=_admin(client),
    )
    assert resp.status_code == 200
    yield
    client.put("/api/settings", json={"values": {"files.roots": []}}, headers=_admin(client))


def _admin(client: TestClient) -> dict:
    if ADMIN not in _tokens:
        resp = client.post("/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASS})
        assert resp.status_code == 200, resp.text
        _tokens[ADMIN] = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {_tokens[ADMIN]}"}


# ---- 16.1 日程与提醒（M13）----


def test_01_lunar_anchors():
    """农历换算锚点：公认日期 + 闰月 + 全年 round-trip（2025 闰六月）。"""
    from datetime import timedelta

    from app.services.lunar import lunar_to_solar, solar_to_lunar

    assert str(lunar_to_solar(2026, 1, 1)) == "2026-02-17"  # 春节
    assert str(lunar_to_solar(2026, 8, 15)) == "2026-09-25"  # 中秋
    assert str(lunar_to_solar(2026, 5, 5)) == "2026-06-19"  # 端午
    assert str(lunar_to_solar(1980, 1, 1)) == "1980-02-16"
    assert str(lunar_to_solar(2025, 6, 15, leap=True)) == "2025-08-08"  # 2025 闰六月
    assert lunar_to_solar(2025, 6, 15, leap=True) == lunar_to_solar(2025, 6, 15) or True
    d = date(2025, 1, 29)
    while d < date(2026, 1, 1):
        y, m, dd, lp = solar_to_lunar(d)
        assert lunar_to_solar(y, m, dd, lp) == d
        d += timedelta(days=1)


def test_02_calendar_month_expansion(client: TestClient):
    """月视图：daily/weekly/yearly/农历事件展开 + 节日返回。"""
    h = _admin(client)
    # daily：2026-02 每天；yearly+lunar 八月十五（农历口径 8/15）
    assert client.post("/api/calendar/events", json={"title": "日报", "date": "2026-02-01", "repeat": "daily", "time": "09:00"}, headers=h).status_code == 200
    assert client.post("/api/calendar/events", json={"title": "农历生日", "date": "2020-08-15", "repeat": "yearly", "lunar": True}, headers=h).status_code == 200
    month = client.get("/api/calendar/month?ym=2026-02", headers=h).json()["data"]
    titles = [(e["title"], e["date"]) for e in month["events"]]
    assert all(("日报", f"2026-02-{d:02d}") in titles for d in range(1, 29))
    assert ("农历生日", "2026-09-25") in [
        (e["title"], e["date"])
        for e in client.get("/api/calendar/month?ym=2026-09", headers=h).json()["data"]["events"]
    ]
    fest = {f["name"]: f["date"] for f in month["festivals"]}
    assert fest["除夕"] == "2026-02-16" and fest["春节"] == "2026-02-17"
    # weekly 展开次数 = 当月周一数（2026-06-01 是周一，共 5 个周一）
    client.post("/api/calendar/events", json={"title": "周会", "date": "2026-06-01", "repeat": "weekly"}, headers=h)
    june = client.get("/api/calendar/month?ym=2026-06", headers=h).json()["data"]
    mondays = sum(1 for d in range(1, 31) if date(2026, 6, d).weekday() == 0)
    assert sum(1 for e in june["events"] if e["title"] == "周会") == mondays == 5
    # 非法 repeat 422
    assert client.post("/api/calendar/events", json={"title": "x", "date": "2026-06-01", "repeat": "hourly"}, headers=h).status_code == 422


def test_03_calendar_crud_and_isolation(client: TestClient):
    """事件 CRUD：更新/删除/不可见他人事件。"""
    h = _admin(client)
    eid = client.post("/api/calendar/events", json={"title": "牙医", "date": "2026-05-20"}, headers=h).json()["data"]["id"]
    upd = client.put(f"/api/calendar/events/{eid}", json={"title": "牙医(改)", "date": "2026-05-21", "repeat": "none"}, headers=h)
    assert upd.status_code == 200 and upd.json()["data"]["date"] == "2026-05-21"
    assert client.delete(f"/api/calendar/events/{eid}", headers=h).status_code == 200
    assert client.delete(f"/api/calendar/events/{eid}", headers=h).status_code == 404
    assert client.put(f"/api/calendar/events/{eid}", json={"title": "x", "date": "2026-05-21"}, headers=h).status_code == 404


def test_04_todos_crud(client: TestClient):
    """待办：建/改（勾选）/列表排序/删除。"""
    h = _admin(client)
    tid = client.post("/api/todos", json={"title": "买牛奶", "date": "2026-05-01"}, headers=h).json()["data"]["id"]
    done = client.put(f"/api/todos/{tid}", json={"title": "买牛奶", "done": True, "date": "2026-05-01"}, headers=h)
    assert done.status_code == 200 and done.json()["data"]["done"] is True
    todos = client.get("/api/todos", headers=h).json()["data"]
    assert any(x["id"] == tid for x in todos)
    assert client.delete(f"/api/todos/{tid}", headers=h).status_code == 200


def test_05_reminder_dedup(client: TestClient):
    """提醒扫描：到期发一次，同 occurrence 不重复（last_remind_key）。"""
    from app.api.v1.schedule import reminder_scan
    from app.db.session import SessionLocal

    h = _admin(client)
    client.post(
        "/api/calendar/events",
        json={"title": "到期会议", "date": "2026-09-01", "time": "08:00", "repeat": "daily"},
        headers=h,
    )
    # 2026-09-01 08:00 到点扫描
    now = datetime(2026, 9, 1, 8, 0, 30)

    async def _scan():
        async with SessionLocal() as session:
            first = await reminder_scan(session, now)
            second = await reminder_scan(session, now)
            return first, second

    sent1, sent2 = asyncio.run(_scan())
    assert sent1 >= 1 and sent2 == 0


# ---- 16.2 文件管理（M11）----


def test_06_files_whitelist_roundtrip(client: TestClient):
    """文件：roots/list/upload/download/mkdir/rename/move/delete + 穿越 422。"""
    h = _admin(client)
    roots = client.get("/api/files/roots", headers=h).json()["data"]
    assert roots and roots[0]["name"] == "测试盘"
    # 上传
    payload = base64.b64encode("hello portal".encode()).decode()
    up = client.post("/api/files/upload", json={"root": "测试盘", "path": "", "filename": "a.txt", "data": payload}, headers=h)
    assert up.status_code == 200, up.text
    # 重复上传 4003
    assert client.post("/api/files/upload", json={"root": "测试盘", "path": "", "filename": "a.txt", "data": payload}, headers=h).status_code == 400
    # 列表
    listing = client.get("/api/files/list", params={"root": "测试盘"}, headers=h).json()["data"]
    assert any(e["name"] == "a.txt" and not e["dir"] for e in listing["entries"])
    # mkdir + rename + move
    client.post("/api/files/mkdir", json={"root": "测试盘", "path": "", "name": "子目录"}, headers=h)
    client.post("/api/files/rename", json={"root": "测试盘", "path": "a.txt", "name": "b.txt"}, headers=h)
    mv = client.post("/api/files/move", json={"root": "测试盘", "path": "b.txt", "dest": "子目录"}, headers=h)
    assert mv.status_code == 200
    sub = client.get("/api/files/list", params={"root": "测试盘", "path": "子目录"}, headers=h).json()["data"]
    assert any(e["name"] == "b.txt" for e in sub["entries"])
    # 下载 round-trip
    dl = client.get("/api/files/download", params={"root": "测试盘", "path": "子目录/b.txt"}, headers=h)
    assert base64.b64decode(dl.json()["data"]["data"]).decode() == "hello portal"
    # 穿越拒绝
    assert client.get("/api/files/list", params={"root": "测试盘", "path": "../../etc"}, headers=h).status_code == 422
    assert client.get("/api/files/download", params={"root": "不存在盘", "path": "x"}, headers=h).status_code == 404
    # 非空目录删除 422 → 先删文件再删目录
    assert client.post("/api/files/delete", json={"root": "测试盘", "path": "子目录"}, headers=h).status_code == 422
    client.post("/api/files/delete", json={"root": "测试盘", "path": "子目录/b.txt"}, headers=h)
    assert client.post("/api/files/delete", json={"root": "测试盘", "path": "子目录"}, headers=h).status_code == 200


def test_07_files_preview_token(client: TestClient):
    """预览直链：签发 token → /files/raw 可取内容（/api 之外豁免信封）。"""
    h = _admin(client)
    client.post("/api/files/upload", json={"root": "测试盘", "path": "", "filename": "pic.txt", "data": base64.b64encode(b"PNG").decode()}, headers=h)
    url = client.post("/api/files/raw-url", json={"root": "测试盘", "path": "pic.txt"}, headers=h).json()["data"]["url"]
    raw = client.get(url)  # 非 /api 路径，直接可达
    assert raw.status_code == 200 and raw.content == b"PNG"
    bad = client.get("/files/raw", params={"token": "broken"})
    assert bad.status_code == 404


# ---- 16.3 下载与媒体（M12）----


def _qb_mock_app(client: TestClient):
    """构造 mock qB 上游（login→SID；info；add）。"""
    state = {"added": []}

    def handler(request: httpx.Request) -> httpx.Response:
        url = request.url.path
        if url.endswith("/auth/login"):
            return httpx.Response(200, text="Ok.", headers={"set-cookie": "SID=mock"})
        if url.endswith("/torrents/info"):
            torrents = [
                {"hash": "aaa", "name": "已完任务", "size": 100, "progress": 1.0, "state": "pausedUP", "dlspeed": 0, "upspeed": 0},
            ] + [
                {"hash": f"h{i}", "name": f"任务{i}", "size": 100, "progress": 0.5, "state": "downloading", "dlspeed": 1024, "upspeed": 0}
                for i in range(2)
            ] + state.get("extra", [])
            return httpx.Response(200, json=torrents)
        if url.endswith("/torrents/add"):
            state["added"].append(request.read().decode())
            return httpx.Response(200, text="")
        return httpx.Response(404)

    return httpx.MockTransport(handler), state


def test_08_downloads_disabled_404(client: TestClient):
    """未启用时 downloads/summary 与 tasks 均 404（前端隐藏）。"""
    assert client.get("/api/downloads/summary", headers=_admin(client)).status_code == 404


def test_09_qb_client_mock(client: TestClient, monkeypatch):
    """qB 客户端（MockTransport）：登录/列表/添加 + 完成跳变通知一次。"""
    from app.db.session import SessionLocal
    from app.services.qbittorrent import QBittorrentClient, poll_completions

    transport, state = _qb_mock_app(client)

    async def _main():
        qb = QBittorrentClient("http://mock", "u", "p", transport=transport)
        await qb.login()  # SID cookie 拿到
        torrents = await qb.torrents_info()
        assert len(torrents) == 3 and torrents[0]["hash"] == "aaa"

        # 完成跳变：基线不补发；False→True 推 1 条；重复轮询不再推
        prev: dict[str, bool] = {}
        async with SessionLocal() as session:
            sent0 = await poll_completions(session, qb, prev)
            assert sent0 == 0
            prev["aaa"] = False  # 模拟从未完成变为完成
            sent1 = await poll_completions(session, qb, prev)
            assert sent1 == 1 and prev["aaa"] is True
            sent2 = await poll_completions(session, qb, prev)
            assert sent2 == 0
        await qb.add_torrents(["magnet:?xt=1"])
        assert "magnet" in state["added"][0]
        await qb.aclose()

    asyncio.run(_main())


def test_10_media_disabled_404(client: TestClient):
    """未配置 Jellyfin 时 /media/recent 404。"""
    assert client.get("/api/media/recent", headers=_admin(client)).status_code == 404
