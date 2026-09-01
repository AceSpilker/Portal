"""pytest 全局配置：在导入应用前把 DATA_DIR 指向临时目录，避免污染真实数据。"""
import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="portal-test-")

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    """应用级测试客户端（触发 lifespan 建表）。"""
    with TestClient(app) as c:
        yield c

