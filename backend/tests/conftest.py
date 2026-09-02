"""pytest 全局配置：在导入应用前注入测试环境变量，避免污染真实数据。

传输加密默认关闭（现有接口测试按明文契约断言）；
加密链路本身由 test_crypto.py 单独开启并验证。
"""
import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="portal-test-")
os.environ["SECURITY__ENCRYPT_ENABLED"] = "false"

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    """应用级测试客户端（触发 lifespan 建表）。"""
    with TestClient(app) as c:
        yield c


