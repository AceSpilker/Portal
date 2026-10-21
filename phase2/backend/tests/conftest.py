"""tests 全局 fixtures（测试环境隔离见 config/test_settings.py）。"""

import django  # noqa: E402

django.setup()

import httpx  # noqa: E402
import pytest  # noqa: E402

from config.asgi import application  # noqa: E402


@pytest.fixture
async def asgi_client():
    """全栈 ASGI 测试客户端（含加密中间件；Django test Client 不经过外层 ASGI）。"""
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
