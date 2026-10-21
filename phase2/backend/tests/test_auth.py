"""D2 关卡：认证全链路（init → login → me/user-info → refresh → 改密踢线 → 限流 → TOTP → 会话）。

同一期 test_auth 契约（错误码/双轨 HTTP 状态）+ 二期 ADP 增量（userName 别名、
token/refreshToken 超集、/api/user/info roles 映射、裸 Authorization 头）。
测试口令为运行期随机生成（临时库专用，无真实凭据落源码）。
"""

import asyncio
import secrets
import time

import httpx
import pytest

from apps.accounts import totp as totp_svc
from apps.accounts.models import ApiToken, User, UserSession
from apps.core.models import Setting
from apps.core.ratelimit import reset as rl_reset

ADMIN_USER = "admin"

# 全模块触库；transaction=True：异步 ORM 经 sync_to_async 在线程池连接执行，
# 测试事务包裹会引发 sqlite 跨连接写锁（记 D2 决策），隔离改由 _clean_db 清表保证
pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _clean_db(db):
    User.objects.all().delete()  # 级联清 user_sessions/api_tokens
    Setting.objects.all().delete()
    ApiToken.objects.all().delete()
    UserSession.objects.all().delete()
    # 重置 sqlite 自增序列，保证 userId 等断言确定性（AUTOINCREMENT 计数器独立于数据）
    from django.db import connection

    with connection.cursor() as cur:
        cur.executemany(
            "DELETE FROM sqlite_sequence WHERE name = ?",
            [("users",), ("user_sessions",), ("api_tokens",), ("settings",)],
        )
    yield


def _gen_pass(prefix: str) -> str:
    """随机测试口令：满足强度校验（≥8 位、含字母与数字）。"""
    return f"{prefix}{secrets.token_hex(6)}9x"


ADMIN_PASS = _gen_pass("Ap")
NEW_PASS = _gen_pass("Np")
WRONG_PASS = _gen_pass("Wp")
OTHER_PASS = _gen_pass("Op")

_test_ip = "127.0.0.1"  # httpx ASGITransport 的 scope client


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """每用例前清空登录限流（一期 conftest 同款理由：套件级联锁定）。"""
    asyncio.run(rl_reset(_test_ip))
    asyncio.run(rl_reset("testclient"))
    yield


async def _init(client: httpx.AsyncClient) -> dict:
    resp = await client.post(
        "/api/auth/init",
        json={"site_name": "Portal", "username": ADMIN_USER, "password": ADMIN_PASS},
    )
    assert resp.status_code == 200
    return resp.json()["data"]


async def _login(client: httpx.AsyncClient, **overrides) -> httpx.Response:
    payload = {"username": ADMIN_USER, "password": ADMIN_PASS}
    payload.update(overrides)
    return await client.post("/api/auth/login", json=payload)


# ---- 初始化与登录 ----


async def test_01_init_and_login_superset(asgi_client):
    data = await _init(asgi_client)
    # ADP 超集：camelCase 与一期 snake_case 并存
    assert data["token"] and data["refreshToken"]
    assert data["access_token"] == data["token"]
    assert data["user"]["role"] == "admin"

    resp = await _login(asgi_client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["data"]["token"] and body["data"]["refreshToken"]


async def test_02_login_with_adp_user_name_alias(asgi_client):
    await _init(asgi_client)
    resp = await asgi_client.post(
        "/api/auth/login", json={"userName": ADMIN_USER, "password": ADMIN_PASS}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["user"]["username"] == ADMIN_USER


async def test_03_init_twice_1005(asgi_client):
    await _init(asgi_client)
    resp = await asgi_client.post(
        "/api/auth/init", json={"site_name": "x", "username": "other1", "password": OTHER_PASS}
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 1005


async def test_04_bad_credentials_1001(asgi_client):
    await _init(asgi_client)
    resp = await _login(asgi_client, password=WRONG_PASS)
    assert resp.status_code == 401
    assert resp.json()["code"] == 1001


async def test_05_login_rate_limit_1006(asgi_client):
    await _init(asgi_client)
    for _ in range(5):
        await _login(asgi_client, password=WRONG_PASS)
    resp = await _login(asgi_client, password=WRONG_PASS)
    assert resp.status_code == 429
    assert resp.json()["code"] == 1006


async def test_06_auth_config_public(asgi_client):
    resp = await asgi_client.get("/api/auth/config")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data == {"allow_register": False, "oidc_enabled": False, "ldap_enabled": False}


# ---- me / user-info / 裸 Authorization ----


async def _access(client: httpx.AsyncClient) -> str:
    body = (await _login(client)).json()["data"]
    return body["token"]


async def test_07_me_and_bare_authorization(asgi_client):
    await _init(asgi_client)
    token = await _access(asgi_client)
    # 裸 token（ADP 拦截器形态）
    resp = await asgi_client.get("/api/auth/me", headers={"Authorization": token})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["username"] == ADMIN_USER and data["role"] == "admin"
    # Bearer 前缀（一期形态）
    resp2 = await asgi_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp2.status_code == 200


async def test_08_user_info_adp_contract(asgi_client):
    await _init(asgi_client)
    token = await _access(asgi_client)
    resp = await asgi_client.get("/api/user/info", headers={"Authorization": token})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["userId"] == 1
    assert data["userName"] == ADMIN_USER
    assert data["roles"] == ["R_ADMIN"]
    assert data["buttons"] == []


async def test_09_me_without_token_1002(asgi_client):
    await _init(asgi_client)
    resp = await asgi_client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == 1002


# ---- refresh / logout ----


async def test_10_refresh_flow(asgi_client):
    await _init(asgi_client)
    data = (await _login(asgi_client)).json()["data"]
    resp = await asgi_client.post(
        "/api/auth/refresh", headers={"Authorization": f"Bearer {data['refreshToken']}"}
    )
    assert resp.status_code == 200
    new_access = resp.json()["data"]["access_token"]
    me = await asgi_client.get("/api/auth/me", headers={"Authorization": new_access})
    assert me.status_code == 200
    # 用 access 当 refresh → 1002
    bad = await asgi_client.post(
        "/api/auth/refresh", headers={"Authorization": f"Bearer {new_access}"}
    )
    assert bad.status_code == 401
    assert bad.json()["code"] == 1002


async def test_11_logout_blacklist(asgi_client):
    await _init(asgi_client)
    token = await _access(asgi_client)
    resp = await asgi_client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    after = await asgi_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert after.status_code == 401
    assert after.json()["code"] == 1003


# ---- 改密踢全端 ----


async def test_12_change_password_kicks_all_sessions(asgi_client):
    await _init(asgi_client)
    token = await _access(asgi_client)
    resp = await asgi_client.put(
        "/api/auth/password",
        json={"old_password": ADMIN_PASS, "new_password": NEW_PASS},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    old = await asgi_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert old.status_code == 401
    assert old.json()["code"] == 1003
    # 新密码可登录
    resp2 = await _login(asgi_client, password=NEW_PASS)
    assert resp2.status_code == 200


# ---- TOTP ----


async def test_13_totp_full_flow_1007(asgi_client):
    await _init(asgi_client)
    token = await _access(asgi_client)
    h = {"Authorization": f"Bearer {token}"}
    # setup → otpauth URI
    setup = await asgi_client.post("/api/auth/totp/setup", headers=h)
    assert setup.status_code == 200
    secret = setup.json()["data"]["secret"]
    assert setup.json()["data"]["otpauth_uri"].startswith("otpauth://totp/")
    # enable（当前窗口有效码）→ 恢复码一次展示
    code = totp_svc._code_at(secret, int(time.time() // totp_svc.STEP))
    enable = await asgi_client.post("/api/auth/totp/enable", json={"code": code}, headers=h)
    assert enable.status_code == 200
    codes = enable.json()["data"]["recovery_codes"]
    assert len(codes) == 8
    # 启用后未带 code 登录 → 1007
    resp = await _login(asgi_client)
    assert resp.status_code == 422
    assert resp.json()["code"] == 1007
    # 错误 code → 2001
    bad = await _login(asgi_client, totp_code="999999")
    assert bad.status_code == 422
    assert bad.json()["code"] == 2001
    # 正确验证码登录成功
    ok_login = await _login(asgi_client, totp_code=code)
    assert ok_login.status_code == 200


# ---- 会话管理 ----


async def test_14_sessions_list_and_revoke(asgi_client):
    await _init(asgi_client)
    token = await _access(asgi_client)
    h = {"Authorization": f"Bearer {token}"}
    lst = await asgi_client.get("/api/auth/sessions", headers=h)
    assert lst.status_code == 200
    items = lst.json()["data"]
    assert len(items) >= 1
    sid = items[0]["id"]
    # 吊销旧会话；新登录会话 jti 不同不受影响
    data = (await _login(asgi_client)).json()["data"]
    revoke = await asgi_client.delete(f"/api/auth/sessions/{sid}", headers=h)
    assert revoke.status_code == 200
    resp = await asgi_client.post(
        "/api/auth/refresh", headers={"Authorization": f"Bearer {data['refreshToken']}"}
    )
    assert resp.status_code == 200
