"""测试专用设置（pytest.ini 指定；pytest-django 在 initial-conftest 阶段即加载 settings，
环境变量引导来不及——Django 迁移期的关键差异，记 D0.8 决策）。

- 独立临时 DATA_DIR（绝不触碰真实数据/密钥）；
- 加密默认关闭（全量明文契约跑；加密链路由 test_crypto.py 用 override_settings 单独开启）。
"""

from __future__ import annotations

import secrets
import tempfile
from pathlib import Path

from config.settings import *  # noqa: F401,F403

DATA_DIR = Path(tempfile.mkdtemp(prefix="portal2-test-"))

# 测试签名密钥：进程内随机（≥32 字节，满足 HMAC-SHA256 长度建议），无真实凭据落源码
SECRET_KEY = secrets.token_hex(32)

ENCRYPT_ENABLED = False

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "data.db",
        "OPTIONS": {"timeout": 20, "init_command": "PRAGMA journal_mode=WAL;"},
    }
}
