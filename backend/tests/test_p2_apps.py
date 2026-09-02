"""P2 测试关卡：应用、分组与入口管理（dev-plan P2 单元测试）。

文件名以 p2 开头保证字母序在 test_auth/test_crypto/test_health 之后执行；
admin 密码经直接改库重置为已知值，与前置用例的改密链路解耦。

测试顺序即业务链路：权限 → 分组 CRUD/排序幂等 → 应用 CRUD/过滤/可见性 →
入口 CRUD/类型校验 → 图标上传压缩 → favicon 抓取兜底 → 导出导入 round-trip →
软删除 → 分组删除解绑。
"""

import asyncio
import base64
import io
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import settings
from app.core.security import hash_password
from app.services import icon as icon_service

ADMIN_USER = "admin"
ADMIN_PASS = "portal-p2"
ALICE_USER = "alice"
ALICE_PASS = "alice12345"

_ids: dict = {}  # 跨用例共享资源 id
_tokens: dict = {}


def _reset_db_state() -> None:
    """同步 sqlite3 直改库（绕开异步引擎/事件循环）：确保 admin/alice 账号可用。

    admin 密码重置为已知值——既覆盖前置用例改密后的状态（全家桶运行），
    也覆盖本文件单独运行时库内无用户的情形。
    """
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
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (ALICE_USER,)).fetchone() is None:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, is_active, prefs, token_version)"
                " VALUES (?, ?, 'user', 1, '{}', 0)",
                (ALICE_USER, hash_password(ALICE_PASS)),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="module", autouse=True)
def _setup(client: TestClient):
    """建表（client lifespan）之后再重置账号状态；缓存 token 一并作废。"""
    _reset_db_state()
    _tokens.clear()


def _admin(client: TestClient) -> dict:
    if "admin" not in _tokens:
        resp = client.post("/api/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
        assert resp.status_code == 200, resp.text
        _tokens["admin"] = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {_tokens['admin']}"}


def _alice(client: TestClient) -> dict:
    if "alice" not in _tokens:
        resp = client.post("/api/auth/login", json={"username": ALICE_USER, "password": ALICE_PASS})
        assert resp.status_code == 200, resp.text
        _tokens["alice"] = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {_tokens['alice']}"}


# ============ 权限 ============


def test_01_read_requires_auth(client: TestClient):
    assert client.get("/api/categories").status_code == 401
    assert client.get("/api/apps").status_code == 401


def test_02_write_requires_admin(client: TestClient):
    resp = client.post("/api/categories", json={"name": "x"}, headers=_alice(client))
    assert resp.status_code == 403
    assert resp.json()["code"] == 3001
    # 普通用户可读
    assert client.get("/api/categories", headers=_alice(client)).status_code == 200


# ============ 分组（M03-2/4）============


def test_03_create_categories(client: TestClient):
    for name in ("媒体", "工具", "开发"):
        resp = client.post(
            "/api/categories", json={"name": name, "icon": "📁"}, headers=_admin(client)
        )
        assert resp.status_code == 200, resp.text
        _ids[f"cat-{name}"] = resp.json()["data"]["id"]
    data = client.get("/api/categories", headers=_admin(client)).json()["data"]
    assert [c["name"] for c in data] == ["媒体", "工具", "开发"]
    assert all(c["app_count"] == 0 for c in data)


def test_04_duplicate_category_name(client: TestClient):
    resp = client.post("/api/categories", json={"name": "媒体"}, headers=_admin(client))
    assert resp.json()["code"] == 4002


def test_05_update_category(client: TestClient):
    cid = _ids["cat-媒体"]
    resp = client.put(f"/api/categories/{cid}", json={"icon": "🎬"}, headers=_admin(client))
    assert resp.status_code == 200
    assert resp.json()["data"]["icon"] == "🎬"
    # 改成已存在的名字 → 4002
    resp = client.put(f"/api/categories/{cid}", json={"name": "工具"}, headers=_admin(client))
    assert resp.json()["code"] == 4002


def test_06_category_sort_idempotent(client: TestClient):
    items = [
        {"id": _ids["cat-媒体"], "sort": 2},
        {"id": _ids["cat-工具"], "sort": 0},
        {"id": _ids["cat-开发"], "sort": 1},
    ]
    for _ in range(2):  # 重复提交结果一致（幂等）
        resp = client.put("/api/categories/sort", json={"items": items}, headers=_admin(client))
        assert resp.status_code == 200
        data = client.get("/api/categories", headers=_admin(client)).json()["data"]
        assert [c["name"] for c in data] == ["工具", "开发", "媒体"]


# ============ 应用（M03-1/4）============


def _create_app(client: TestClient, **overrides) -> dict:
    payload = {
        "name": "Jellyfin",
        "description": "媒体服务器",
        "category_id": _ids["cat-媒体"],
        "icon_type": "emoji",
        "icon": "🎬",
        "health_type": "http",
        "health_target": "http://192.168.1.10:8096",
        "health_interval": 60,
        "open_mode": "newtab",
        "visibility": "all",
        "tags": ["媒体", "影音"],
    } | overrides
    resp = client.post("/api/apps", json=payload, headers=_admin(client))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_07_create_and_get_app(client: TestClient):
    app = _create_app(client)
    _ids["app-jellyfin"] = app["id"]
    assert app["icon_type"] == "emoji" and app["enabled"] is True
    detail = client.get(f"/api/apps/{app['id']}", headers=_admin(client)).json()["data"]
    assert detail["name"] == "Jellyfin"
    assert detail["urls"] == []
    assert detail["tags"] == ["媒体", "影音"]


def test_08_app_validation(client: TestClient):
    # 非法 open_mode
    resp = client.post(
        "/api/apps", json={"name": "x", "open_mode": "popup"}, headers=_admin(client)
    )
    assert resp.status_code == 422
    # 空名称
    resp = client.post("/api/apps", json={"name": "  "}, headers=_admin(client))
    assert resp.status_code == 422
    # 分组不存在
    resp = client.post(
        "/api/apps", json={"name": "x", "category_id": 99999}, headers=_admin(client)
    )
    assert resp.json()["code"] == 4001


def test_09_update_app(client: TestClient):
    aid = _ids["app-jellyfin"]
    resp = client.put(
        f"/api/apps/{aid}",
        json={"description": "家庭媒体中心", "favorite": True},
        headers=_admin(client),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["description"] == "家庭媒体中心"
    assert data["favorite"] is True


def test_10_app_sort_idempotent(client: TestClient):
    qb = _create_app(client, name="qBittorrent", category_id=_ids["cat-工具"], tags=[])
    ha = _create_app(client, name="Home Assistant", category_id=_ids["cat-开发"], tags=[])
    _ids["app-qb"], _ids["app-ha"] = qb["id"], ha["id"]
    items = [
        {"id": _ids["app-jellyfin"], "sort": 5, "category_id": _ids["cat-媒体"]},
        {"id": _ids["app-qb"], "sort": 6, "category_id": _ids["cat-媒体"]},  # 移动分组
        {"id": _ids["app-ha"], "sort": 7, "category_id": _ids["cat-开发"]},
    ]
    for _ in range(2):  # 幂等
        resp = client.put("/api/apps/sort", json={"items": items}, headers=_admin(client))
        assert resp.status_code == 200
        apps = {a["id"]: a for a in client.get("/api/apps", headers=_admin(client)).json()["data"]}
        assert apps[_ids["app-jellyfin"]]["sort"] == 5
        assert apps[_ids["app-qb"]]["category_id"] == _ids["cat-媒体"]
        assert apps[_ids["app-ha"]]["sort"] == 7


def test_11_list_filters_and_visibility(client: TestClient):
    admin_only = _create_app(
        client, name="SecretPanel", visibility="admin", category_id=None, tags=[]
    )
    _ids["app-secret"] = admin_only["id"]

    admin_list = client.get("/api/apps", headers=_admin(client)).json()["data"]
    alice_list = client.get("/api/apps", headers=_alice(client)).json()["data"]
    assert "SecretPanel" in [a["name"] for a in admin_list]
    assert "SecretPanel" not in [a["name"] for a in alice_list]
    # 详情同样受可见性约束
    resp = client.get(f"/api/apps/{_ids['app-secret']}", headers=_alice(client))
    assert resp.json()["code"] == 4001

    # 关键词：名称 / 标签
    kw = client.get("/api/apps?keyword=jelly", headers=_admin(client)).json()["data"]
    assert [a["name"] for a in kw] == ["Jellyfin"]
    kw = client.get("/api/apps?keyword=影音", headers=_admin(client)).json()["data"]
    assert [a["name"] for a in kw] == ["Jellyfin"]
    # 分组过滤
    kw = client.get(f"/api/apps?category={_ids['cat-媒体']}", headers=_admin(client)).json()["data"]
    assert {a["name"] for a in kw} == {"Jellyfin", "qBittorrent"}
    # 标签参数过滤
    kw = client.get("/api/apps?tag=媒体", headers=_admin(client)).json()["data"]
    assert [a["name"] for a in kw] == ["Jellyfin"]


# ============ 访问入口（M04-1~6）============


def test_12_url_crud(client: TestClient):
    aid = _ids["app-jellyfin"]
    lan = client.post(
        f"/api/apps/{aid}/urls",
        json={"access_type": "lan", "url": "http://192.168.1.10:8096", "label": "内网直连"},
        headers=_admin(client),
    )
    assert lan.status_code == 200, lan.text
    domain = client.post(
        f"/api/apps/{aid}/urls",
        json={"access_type": "domain", "url": "https://jf.example.com", "label": "公网域名"},
        headers=_admin(client),
    )
    assert domain.status_code == 200
    _ids["url-lan"] = lan.json()["data"]["id"]
    _ids["url-domain"] = domain.json()["data"]["id"]

    urls = client.get(f"/api/apps/{aid}/urls", headers=_admin(client)).json()["data"]
    assert [u["access_type"] for u in urls] == ["lan", "domain"]  # sort 自动递增
    detail = client.get(f"/api/apps/{aid}", headers=_admin(client)).json()["data"]
    assert len(detail["urls"]) == 2  # 详情聚合入口

    resp = client.put(
        f"/api/app-urls/{_ids['url-domain']}",
        json={"label": "外网域名", "sort": 0},
        headers=_admin(client),
    )
    assert resp.status_code == 200
    urls = client.get(f"/api/apps/{aid}/urls", headers=_admin(client)).json()["data"]
    assert urls[0]["label"] == "外网域名" and urls[0]["access_type"] == "domain"

    resp = client.delete(f"/api/app-urls/{_ids['url-domain']}", headers=_admin(client))
    assert resp.status_code == 200
    urls = client.get(f"/api/apps/{aid}/urls", headers=_admin(client)).json()["data"]
    assert len(urls) == 1
    _ids["url-domain"] = client.post(  # 重新补上，供导入导出用例使用
        f"/api/apps/{aid}/urls",
        json={"access_type": "domain", "url": "https://jf.example.com", "label": "公网域名"},
        headers=_admin(client),
    ).json()["data"]["id"]


def test_13_url_validation(client: TestClient):
    aid = _ids["app-jellyfin"]
    # 五种类型之外拒绝
    resp = client.post(
        f"/api/apps/{aid}/urls",
        json={"access_type": "ftp", "url": "ftp://x"},
        headers=_admin(client),
    )
    assert resp.status_code == 422
    # 空 url 拒绝
    resp = client.post(
        f"/api/apps/{aid}/urls",
        json={"access_type": "lan", "url": " "},
        headers=_admin(client),
    )
    assert resp.status_code == 422
    # 应用不存在
    resp = client.post(
        "/api/apps/99999/urls",
        json={"access_type": "lan", "url": "http://x"},
        headers=_admin(client),
    )
    assert resp.json()["code"] == 4001
    # 普通用户不能写入口
    resp = client.put(
        f"/api/app-urls/{_ids['url-lan']}",
        json={"label": "hack"},
        headers=_alice(client),
    )
    assert resp.status_code == 403


# ============ 图标体系（M03-5/6）============


def _png_bytes(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), (91, 95, 241))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_14_upload_icon_compressed_square(client: TestClient):
    raw = _png_bytes(300, 200)  # 非方形 → 应居中裁方压缩为 128x128
    resp = client.post(
        "/api/apps/upload-icon",
        json={"filename": "jellyfin.png", "data": base64.b64encode(raw).decode()},
        headers=_admin(client),
    )
    assert resp.status_code == 200, resp.text
    url_path = resp.json()["data"]["url"]
    assert url_path.startswith("/icons/")
    file = Path(settings.data_dir) / "icons" / Path(url_path).name
    assert file.is_file()
    with Image.open(file) as im:
        assert im.size == (128, 128)

    # 挂到应用（upload 类型）
    resp = client.put(
        f"/api/apps/{_ids['app-jellyfin']}",
        json={"icon": url_path, "icon_type": "upload"},
        headers=_admin(client),
    )
    assert resp.status_code == 200
    # 普通用户不允许上传
    resp = client.post(
        "/api/apps/upload-icon",
        json={"filename": "x.png", "data": base64.b64encode(raw).decode()},
        headers=_alice(client),
    )
    assert resp.status_code == 403


def test_15_upload_icon_invalid(client: TestClient):
    resp = client.post(
        "/api/apps/upload-icon",
        json={"filename": "x.png", "data": "!!!not-base64!!!"},
        headers=_admin(client),
    )
    assert resp.status_code == 422
    resp = client.post(
        "/api/apps/upload-icon",
        json={"filename": "x.png", "data": base64.b64encode(b"hello text").decode()},
        headers=_admin(client),
    )
    assert resp.status_code == 422


def test_16_favicon_unreachable_falls_back(client: TestClient):
    """favicon 抓取失败兜底：全部候选不可达 → 业务失败 4004，接口不炸。"""

    def timeout_handler(request):
        raise AssertionError("不应发起真实网络请求")

    async def service_roundtrip():
        # 1) 成功路径：MockTransport 提供 /favicon.ico
        png = _png_bytes(64, 64)

        def ok_handler(request):
            return httpx.Response(200, content=png, headers={"content-type": "image/png"})

        raw = await icon_service.fetch_favicon(
            "http://example.com/", transport=httpx.MockTransport(ok_handler)
        )
        assert raw == png
        url_path = icon_service.save_icon(raw, "favicon.png")
        assert url_path.startswith("/icons/")

        # 2) 超时/连接失败兜底：所有候选均不可达 → 4004
        def fail_handler(request):
            raise httpx.ConnectError("timed out", request=request)

        try:
            await icon_service.fetch_favicon(
                "http://example.com/", transport=httpx.MockTransport(fail_handler)
            )
            raise AssertionError("应当抛出 BizError")
        except icon_service.BizError as exc:
            assert exc.code == 4004

    asyncio.run(service_roundtrip())
    # 非法地址 → 2001
    resp = client.get("/api/apps/favicon?url=ftp://x", headers=_admin(client))
    assert resp.json()["code"] == 2001


# ============ 导入导出（M03-13）============


def test_17_export_import_roundtrip(client: TestClient):
    resp = client.get("/api/apps/export", headers=_admin(client))
    assert resp.status_code == 200
    export1 = resp.json()["data"]
    assert export1["version"] == 1
    assert {c["name"] for c in export1["categories"]} == {"媒体", "工具", "开发"}
    jelly = next(a for a in export1["apps"] if a["name"] == "Jellyfin")
    assert {u["access_type"] for u in jelly["urls"]} == {"lan", "domain"}

    # 普通用户不允许导入导出
    assert client.get("/api/apps/export", headers=_alice(client)).status_code == 403
    assert client.post("/api/apps/import", json=export1, headers=_alice(client)).status_code == 403

    # 覆盖式导入（此时库内已有同量数据）→ 再导出应与首次导出一致
    resp = client.post("/api/apps/import", json=export1, headers=_admin(client))
    assert resp.status_code == 200, resp.text
    result = resp.json()["data"]
    assert result == {
        "categories": len(export1["categories"]),
        "apps": len(export1["apps"]),
        "urls": sum(len(a["urls"]) for a in export1["apps"]),
    }
    export2 = client.get("/api/apps/export", headers=_admin(client)).json()["data"]
    export1.pop("exported_at")
    export2.pop("exported_at")
    assert export1 == export2  # round-trip 一致（含 id）


def test_18_soft_delete(client: TestClient):
    temp = _create_app(client, name="TempApp", category_id=None, tags=[])
    resp = client.delete(f"/api/apps/{temp['id']}", headers=_admin(client))
    assert resp.status_code == 200
    names = [a["name"] for a in client.get("/api/apps", headers=_admin(client)).json()["data"]]
    assert "TempApp" not in names
    assert client.get(f"/api/apps/{temp['id']}", headers=_admin(client)).json()["code"] == 4001
    # 重复删除 → 404（已不在可见列表）
    resp = client.delete(f"/api/apps/{temp['id']}", headers=_admin(client))
    assert resp.json()["code"] == 4001


def test_19_delete_category_detaches_apps(client: TestClient):
    cat = client.post("/api/categories", json={"name": "临时分组"}, headers=_admin(client)).json()
    data = cat["data"]
    app = _create_app(client, name="DetachMe", category_id=data["id"], tags=[])
    resp = client.delete(f"/api/categories/{data['id']}", headers=_admin(client))
    assert resp.status_code == 200
    names = [
        c["name"] for c in client.get("/api/categories", headers=_admin(client)).json()["data"]
    ]
    assert "临时分组" not in names
    detail = client.get(f"/api/apps/{app['id']}", headers=_admin(client)).json()["data"]
    assert detail["category_id"] is None  # 应用保留、移出分组
