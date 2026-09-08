"""pytest 全局配置：在导入应用前注入测试环境变量，避免污染真实数据。

传输加密默认关闭（现有接口测试按明文契约断言）；
加密链路本身由 test_crypto.py 单独开启并验证。
"""

import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="portal-test-")
os.environ["SECURITY__ENCRYPT_ENABLED"] = "false"

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    """每个用例前清空登录限流。

    TestClient 所有请求同 IP（testclient），全量套件中 test_auth::test_16 等
    限流用例会把该 IP 锁 60s，套件越慢级联失败越多（071 实测 133 连锁失败）。
    ratelimit.reset 本就是测试辅助函数，此处自动调用。
    """

    from app.core.ratelimit import is_locked, reset

    asyncio.run(reset("testclient"))
    locked = asyncio.run(is_locked("testclient"))
    if locked:
        print("[conftest] WARN: rate limit STILL locked after reset!")
    yield


@pytest.fixture(scope="session")
def client():
    """应用级测试客户端（触发 lifespan 建表）。"""
    with TestClient(app) as c:
        yield c
