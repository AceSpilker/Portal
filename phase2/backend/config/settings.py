"""Portal 二期 Django 配置（dev-plan D0.1；环境变量键名与一期保持一致，见迁移方案 §3.1）。

与一期的差异：
- FRONTEND_DIST 仅用于可选的本地直连 SPA 视图（生产前端由 nginx 容器托管）；
- 新增 PORTAL_RUN_SCHEDULER（D4：APScheduler 启动守卫）；
- 契约信封为 ADP 形态 code=200/msg（迁移方案 §5.1），业务错误码 1001–5006 与一期相同。
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _env_first(*names: str, default: str = "") -> str:
    """按序取第一个显式设置的环境变量（一期 AliasChoices 语义）。"""
    for n in names:
        if n in os.environ:
            return os.environ[n]
    return default


# ---- 服务（同一期 config.py） ----
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")  # 生产必改
APP_VERSION = os.environ.get("APP_VERSION", "2.0.0")
UPDATE_REPO = os.environ.get("UPDATE_REPO", "AceSpilker/Portal")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "info").upper()
DEBUG = _env_bool("DEBUG", "true")
ALLOWED_HOSTS = ["*"]

# ---- 数据（SQLite 运行主库；MySQL 仅镜像目标 D7；Redis 可选存储 D7） ----
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_TYPE = os.environ.get("DB_TYPE", "sqlite")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "data.db",
        # 与一期一致的务实并发参数（单容器单进程 + WAL）
        "OPTIONS": {"timeout": 20, "init_command": "PRAGMA journal_mode=WAL;"},
    }
}

# ---- 监控采集：宿主机只读挂载（为空则读容器自身，D4 使用） ----
HOST_PROC = os.environ.get("HOST_PROC", "")
HOST_SYS = os.environ.get("HOST_SYS", "")

# ---- 可选模块 ----
DOCKER_SOCK_ENABLED = _env_bool("DOCKER_SOCK_ENABLED")
FRONTEND_DIST = os.environ.get("FRONTEND_DIST", "")  # 可选本地直连 SPA；生产由 nginx 托管
OFFICE_CONVERT_URL = os.environ.get("OFFICE_CONVERT_URL", "")
LAN_SCAN_CIDRS = os.environ.get("LAN_SCAN_CIDRS", "")
PORTAL_RUN_SCHEDULER = _env_bool("PORTAL_RUN_SCHEDULER", "true")

# ---- 传输加密（迁移方案 §5.2：协议与一期逐字一致，密钥文件沿用） ----
_encrypt_raw = _env_first("ENCRYPT_ENABLED", "SECURITY__ENCRYPT_ENABLED", default="true")
ENCRYPT_ENABLED = _encrypt_raw.strip().lower() in ("1", "true", "yes", "on")
TRANSPORT_RSA_BITS = int(os.environ.get("TRANSPORT_RSA_BITS", "3072"))

# ---- Django 应用面（无 admin/session/auth——认证走自研 JWT，D2） ----
INSTALLED_APPS: list[str] = [
    "apps.core",
    "apps.accounts",
]

MIDDLEWARE = [
    "apps.core.middleware.LocaleMiddleware",  # Accept-Language → i18n contextvar（一期同款）
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES: list[dict] = []

USE_TZ = True
TIME_ZONE = "UTC"

USE_I18N = False  # 文案本地化由 apps/core/i18n.py 承担（Accept-Language 约定同一期）
LANGUAGE_CODE = "zh-CN"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# 静态：仅 Django 自身（生产前端在 nginx，collectstatic 近空）
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
}
