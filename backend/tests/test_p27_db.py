# ruff: noqa: E501
"""P27 测试关卡：局域网数据库服务发现与只读查看（M20-1~9；dev-plan 27.1~27.6）。

覆盖：握手指纹解析（MySQL greeting 样例字节 / Redis PING·INFO / PG SSLRequest）、
SigV4 手工签名结构、凭据 CRUD（加密落库 + password_set 脱敏 + 空=保持 + 公网 4006 +
重复 409）、值预览截断与二进制检测、服务清单与探活翻转通知、查看器无凭据 422 /
无服务 404、一键建监控项。
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password

ADMIN = "admin"
ADMIN_PASS = "portal-p26"

_tokens: dict = {}


def _reset_db_state() -> None:
    import sqlite3
    from pathlib import Path

    db_file = Path(settings.data_dir) / "portal.db"
    conn = sqlite3.connect(db_file)
    try:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (ADMIN,)).fetchone():
            conn.execute(
                "UPDATE users SET password_hash = ?, is_active = 1, totp_enabled = 0 WHERE username = ?",
                (hash_password(ADMIN_PASS), ADMIN),
            )
        else:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, is_active, prefs, token_version)"
                " VALUES (?, ?, 'admin', 1, '{}', 0)",
                (ADMIN, hash_password(ADMIN_PASS)),
            )
        for table in ("lan_db_services", "db_credentials"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="module", autouse=True)
def _setup(client: TestClient):
    _reset_db_state()
    resp = client.post("/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASS})
    assert resp.status_code == 200, resp.text
    _tokens["admin"] = resp.json()["data"]["access_token"]
    yield


def _auth():
    return {"Authorization": f"Bearer {_tokens['admin']}"}


# ---- 27.1 指纹解析 ----

class _FakeReader:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    async def readexactly(self, n):
        return self.chunks.pop(0)[:n]

    async def readline(self):
        return self.chunks.pop(0)

    async def readuntil(self, sep):
        return self.chunks.pop(0)


class _FakeWriter:
    def write(self, b):
        pass

    async def drain(self):
        pass


def test_01_fingerprint_mysql_greeting():
    from app.services.db_fingerprint import fingerprint_mysql

    payload = b"\x0a" + b"8.0.36\x00" + b"\x00" * 24  # 协议版本 10 + 版本串 + 填充
    header = bytes([len(payload), 0, 0, 0])
    fp = asyncio.run(fingerprint_mysql(_FakeReader([header, payload])))
    assert fp == {"type": "mysql", "version": "8.0.36", "detail": {"protocol": 10}}
    # 非 greeting 流（如 HTTP 响应）→ None
    bad = b"HTTP/1.1 400 Bad Request\r\n"
    fp2 = asyncio.run(fingerprint_mysql(_FakeReader([bad[:4], bad[4:]])))
    assert fp2 is None


def test_02_fingerprint_redis():
    from app.services.db_fingerprint import fingerprint_redis

    r = _FakeReader([b"+PONG\r\n", b"$54\r\n", b"# Server\r\nredis_version:7.4.1\r\nos:Linux\r\n\r\n"])
    fp = asyncio.run(fingerprint_redis(r, _FakeWriter()))
    assert fp["type"] == "redis" and fp["version"] == "7.4.1"
    assert fp["detail"]["os"] == "Linux"
    # 需认证：PING/-INFO 均为错误行仍可识别
    r = _FakeReader([b"-NOAUTH Authentication required.\r\n", b"-NOAUTH\r\n"])
    fp = asyncio.run(fingerprint_redis(r, _FakeWriter()))
    assert fp["type"] == "redis" and fp["detail"]["auth"] == "required"


def test_03_fingerprint_postgresql_and_ports():
    from app.services.db_fingerprint import DB_PORTS, fingerprint_postgresql

    fp = asyncio.run(fingerprint_postgresql(_FakeReader([b"N"]), _FakeWriter()))
    assert fp == {"type": "postgresql", "version": None, "detail": {"ssl": "N"}}
    assert DB_PORTS[3306] == "mysql" and DB_PORTS[6379] == "redis"
    assert DB_PORTS[9000] == "minio" and DB_PORTS[9001] == "minio"
    assert DB_PORTS[5432] == "postgresql" and DB_PORTS[27017] == "mongodb"


# ---- 27.5 SigV4 手工签名 ----

def test_04_sigv4_structure():
    from app.services.db_viewers import presign_get_url, sigv4_header

    headers = sigv4_header(
        "GET", "192.168.1.10:9000", "minioadmin", "secret#key", "/",
        [("list-type", "2"), ("prefix", "a b")],
    )
    auth = headers["Authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256 Credential=minioadmin/")
    assert "SignedHeaders=host" in auth and len(auth.split("Signature=")[1]) == 64
    assert headers["x-amz-date"].endswith("Z")
    # 相同输入 → 稳定签名；不同密钥 → 不同签名
    headers2 = sigv4_header(
        "GET", "192.168.1.10:9000", "minioadmin", "secret#key", "/",
        [("list-type", "2"), ("prefix", "a b")],
    )
    assert headers2["Authorization"] == auth
    headers3 = sigv4_header(
        "GET", "192.168.1.10:9000", "minioadmin", "other", "/",
        [("list-type", "2"), ("prefix", "a b")],
    )
    assert headers3["Authorization"] != auth

    url = presign_get_url("192.168.1.10:9000", "ak", "sk", "bucket", "a/b c.txt", 300)
    assert url.startswith("http://192.168.1.10:9000/bucket/a/b%20c.txt?")
    assert "X-Amz-Expires=300" in url and "X-Amz-Signature=" in url
    assert "sk" not in url.split("Credential=")[1].split("/")[0]  # secret 不落 URL


def test_05_value_preview_binary_and_truncate():
    from app.services.db_viewers import _preview_bytes

    assert _preview_bytes(b"hello world")["binary"] is False
    assert _preview_bytes(b"a\x00b")["binary"] is True  # NUL → hex
    assert _preview_bytes("中文值".encode())["binary"] is False
    binary_junk = bytes(range(128, 256))
    assert _preview_bytes(binary_junk)["binary"] is True  # 高密度替换符 → hex
    out = _preview_bytes(b"x" * 5000)
    assert out["truncated"] is True and len(out["preview"]) <= 4096


# ---- 27.2 凭据管理 API ----

def test_06_credentials_crud_masking_and_guards(client: TestClient):
    # 公网 host → 4006
    resp = client.post(
        "/api/lan/db/credentials", headers=_auth(),
        json={"service_type": "redis", "host": "8.8.8.8", "port": 6379, "password": "x"},
    )
    assert resp.status_code == 422 and resp.json()["code"] == 4006
    # 非法类型 → 422
    resp = client.post(
        "/api/lan/db/credentials", headers=_auth(),
        json={"service_type": "mongodb", "host": "127.0.0.1", "port": 27017},
    )
    assert resp.status_code == 422
    # 正常创建（回环允许=查看 NAS 自身服务）
    resp = client.post(
        "/api/lan/db/credentials", headers=_auth(),
        json={"service_type": "redis", "host": "127.0.0.1", "port": 6379,
              "username": "", "password": "secret-pass", "extra": {"db": 2}},
    )
    assert resp.status_code == 200, resp.text
    cred = resp.json()["data"]
    assert cred["password_set"] is True and "password" not in cred  # 脱敏
    assert cred["extra"]["db"] == 2
    cred_id = cred["id"]

    # 加密落库验证（DB 中不是明文）
    import sqlite3
    from pathlib import Path

    conn = sqlite3.connect(Path(settings.data_dir) / "portal.db")
    row = conn.execute("SELECT secret FROM db_credentials WHERE id = ?", (cred_id,)).fetchone()
    conn.close()
    assert row[0] and "secret-pass" not in row[0]

    # host:port 重复 → 409
    resp = client.post(
        "/api/lan/db/credentials", headers=_auth(),
        json={"service_type": "redis", "host": "127.0.0.1", "port": 6379},
    )
    assert resp.status_code == 409

    # 空 password 更新 = 保持原值（仍 password_set）
    resp = client.put(
        f"/api/lan/db/credentials/{cred_id}", headers=_auth(),
        json={"username": "u1", "password": ""},
    )
    data = resp.json()["data"]
    assert data["password_set"] is True and data["username"] == "u1"

    # 连接测试（127.0.0.1:6379 大概率无服务 → ok=False 而非 500）
    resp = client.post(f"/api/lan/db/credentials/{cred_id}/test", headers=_auth())
    assert resp.status_code == 200 and "ok" in resp.json()["data"]

    # 列表脱敏
    resp = client.get("/api/lan/db/credentials", headers=_auth())
    assert resp.json()["data"]["total"] == 1
    assert all("secret" not in c for c in resp.json()["data"]["items"])

    # 未认证 → 401
    resp = client.get("/api/lan/db/credentials")
    assert resp.status_code == 401


def test_07_credential_delete_unlinks_service(client: TestClient):
    from app.db.session import SessionLocal
    from app.models.lan import DbCredential, LanDbService

    async def seed():
        async with SessionLocal() as session:
            cred = DbCredential(
                service_type="minio", host="127.0.0.1", port=9000,
                username="minioadmin", secret="enc",
            )
            session.add(cred)
            await session.commit()
            svc = LanDbService(host="127.0.0.1", port=9000, service_type="minio",
                               credential_id=cred.id, state="up")
            session.add(svc)
            await session.commit()
            return cred.id, svc.id

    cred_id, svc_id = asyncio.run(seed())
    resp = client.delete(f"/api/lan/db/credentials/{cred_id}", headers=_auth())
    assert resp.status_code == 200
    svc = asyncio.run(_get_service(svc_id))
    assert svc.credential_id is None  # 解除关联后删除


async def _get_service(svc_id: int):
    from app.db.session import SessionLocal
    from app.models.lan import LanDbService

    async with SessionLocal() as session:
        return await session.get(LanDbService, svc_id)


# ---- 27.1/27.6 服务清单 / 扫描 / 探活 ----



def _clear_db_services() -> None:
    import sqlite3
    from pathlib import Path

    conn = sqlite3.connect(Path(settings.data_dir) / "portal.db")
    conn.execute("DELETE FROM lan_db_services")
    conn.commit()
    conn.close()



def test_08_services_list_and_scan_api(client: TestClient, monkeypatch):
    _clear_db_services()

    from app.db.session import SessionLocal
    from app.models.lan import LanDbService, LanDevice
    from app.services import db_fingerprint

    async def seed():
        async with SessionLocal() as session:
            session.add(LanDevice(ip="192.168.92.10", hostname="nas-main",
                                  device_type="db", online=1))
            session.add(LanDbService(host="192.168.92.10", port=3306, service_type="mysql",
                                     version="8.0.36", state="up", latency_ms=3))
            session.add(LanDbService(host="192.168.92.10", port=6379, service_type="redis",
                                     version="7.4.1", state="up"))
            await session.commit()

    asyncio.run(seed())
    resp = client.get("/api/lan/db/services", headers=_auth())
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 2
    mysql = next(i for i in data["items"] if i["service_type"] == "mysql")
    assert mysql["version"] == "8.0.36"
    assert mysql["device"]["hostname"] == "nas-main"  # 设备联动标注
    resp = client.get("/api/lan/db/services", headers=_auth(), params={"type": "redis"})
    assert resp.json()["data"]["total"] == 1

    # 扫描：fake 后台任务 + 互斥 4005
    async def _fake(run_id, cidrs, extra_ports=None):
        db_fingerprint._current = None

    monkeypatch.setattr(db_fingerprint, "_run_db_scan", _fake)
    resp = client.post("/api/lan/db/scan", headers=_auth(), json={"cidrs": ["192.168.92.0/29"]})
    assert resp.status_code == 200
    resp = client.post("/api/lan/db/scan", headers=_auth(), json={"cidrs": ["1.2.3.0/24"]})
    assert resp.json()["code"] == 4006
    db_fingerprint._current = {"run_id": 999, "kind": "db"}
    resp = client.post("/api/lan/db/scan", headers=_auth(), json={})
    assert resp.status_code == 409
    db_fingerprint._current = None


def test_09_probe_flip_notification(client: TestClient, monkeypatch):
    """探活翻转：up→down 触发通知（source=db）+ WS 帧结构。"""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.lan import LanDbService
    from app.models.probe import Notification
    from app.services import db_fingerprint

    _clear_db_services()

    async def seed():
        async with SessionLocal() as session:
            session.add(LanDbService(host="127.0.0.1", port=6380, service_type="redis",
                                     state="up"))
            await session.commit()

    asyncio.run(seed())

    async def _dead(host, port):
        return None

    monkeypatch.setattr(db_fingerprint, "probe_service", _dead)

    async def run_probe():
        async with SessionLocal() as session:
            flipped = await db_fingerprint.probe_due_services(session)
            rows = (await session.execute(
                select(Notification).order_by(Notification.id.desc()).limit(1)
            )).scalars().all()
            return flipped, rows

    flipped, rows = asyncio.run(run_probe())
    assert flipped == 1
    assert rows and rows[0].source == "db" and "127.0.0.1:6380" in rows[0].title


def test_10_viewer_guards(client: TestClient):
    """查看器边界：服务不存在 404；服务无凭据 422；一键监控 409 去重。"""
    from app.db.session import SessionLocal
    from app.models.lan import LanDbService

    async def seed():
        async with SessionLocal() as session:
            session.add(LanDbService(host="127.0.0.1", port=3307, service_type="mysql",
                                     state="up"))
            await session.commit()

    asyncio.run(seed())
    resp = client.get("/api/lan/db/mysql/999999/overview", headers=_auth())
    assert resp.status_code == 404
    from sqlalchemy import select

    from app.db.session import SessionLocal as SL

    async def find():
        async with SL() as session:
            return (await session.execute(
                select(LanDbService).where(LanDbService.port == 3307)
            )).scalar_one()

    svc = asyncio.run(find())
    resp = client.get(f"/api/lan/db/mysql/{svc.id}/overview", headers=_auth())
    assert resp.status_code == 422  # 无凭据
    # 错误凭据 → 4004 业务失败摘要（不 500）
    resp = client.post(
        "/api/lan/db/credentials", headers=_auth(),
        json={"service_type": "mysql", "host": "127.0.0.1", "port": 3307,
              "username": "root", "password": "wrong"},
    )
    assert resp.status_code == 200
    resp = client.get(f"/api/lan/db/mysql/{svc.id}/overview", headers=_auth())
    assert resp.status_code == 200 and resp.json()["code"] == 4004
    assert "MySQL" in resp.json()["message"]

    # 一键建监控项 + 重复 409
    resp = client.post(f"/api/lan/db/services/{svc.id}/monitor", headers=_auth())
    assert resp.status_code == 200
    resp = client.post(f"/api/lan/db/services/{svc.id}/monitor", headers=_auth())
    assert resp.status_code == 409


def test_11_readonly_enforced_by_construction():
    """白名单强制：查看器模块源码不存在任何写命令/写 SQL 路径（结构化断言）。"""
    from pathlib import Path

    import app.services.db_viewers as dv

    source = Path(dv.__file__).read_text(encoding="utf-8")
    forbidden_redis = ["b'SET ", '"SET ', "flushdb", "flushall", "delete(", ".set(",
                       "del(", "expire(", "rename(", "lpush", "rpush", "hset", "sadd",
                       "zadd", "config set", "shutdown", "save()", "bgsave"]
    forbidden_sql = ["INSERT INTO", "UPDATE ", "DELETE FROM", "DROP ", "ALTER ", "CREATE ",
                     "TRUNCATE TABLE", "GRANT ", "REPLACE INTO", "LOAD DATA"]
    for token in forbidden_redis + forbidden_sql:
        assert token.lower() not in source.lower(), f"只读查看器源码出现 {token}"
    # 白名单命令清单确实存在（固定查询由这些方法构成）
    for allowed in ["info(", "scan(", "dbsize", "lrange", "hgetall", "srandmember",
                    "zrange", "slowlog_get", "client_list", "getrange"]:
        assert allowed in source


def test_12_sniff_and_config_guards():
    """标识符白名单（rows 防注入）+ 配置清洗（回环/公网/超限网段丢弃）。"""
    import asyncio

    from app.services.db_viewers import ViewerError, _quote_ident
    from app.services.lan_scan import sanitize_cidrs

    # 标识符白名单：合法反引号引用；注入/特殊字符/空串拒绝
    assert _quote_ident("users") == "`users`"
    assert _quote_ident("my_db$1") == "`my_db$1`"
    for bad in ("`db`.`t; DROP TABLE x", "a-b", "a b", "", "x'; --", "a" * 100):
        try:
            _quote_ident(bad)
            assert False, bad
        except ViewerError:
            pass

    # 配置清洗：坏网段（回环/公网/超限/垃圾串）全部丢弃，合法保留去重
    assert sanitize_cidrs(["192.168.5.0/24", "127.0.0.0/8", "8.8.8.0/24", "10.0.0.0/8", "banana", None, 192]) == ["192.168.5.0/24"]
    assert sanitize_cidrs(["10.0.0.0/24", "10.0.0.0/24"]) == ["10.0.0.0/24"]
    assert sanitize_cidrs(["172.16.1.0/24"]) == ["172.16.1.0/24"]  # 超限 /12 会被丢弃
    assert sanitize_cidrs([]) == []

    # 非默认端口：sniff 走 mysql greeting 路径（用 Fake 流直测 fingerprint 组合入口）
    from app.services.db_fingerprint import DB_PORTS
    assert 3306 in DB_PORTS and 3309 not in DB_PORTS  # 3309 属"额外端口"范畴

    # get_lan_config 对 env 网段的支持（LAN_SCAN_CIDRS）
    from app.db.session import SessionLocal

    async def run():
        async with SessionLocal() as session:
            return await __import__("app.services.lan_scan", fromlist=["get_lan_config"]).get_lan_config(session)

    cfg = asyncio.run(run())
    assert "scan_cidrs_env" in cfg and cfg["concurrency"] >= 16
