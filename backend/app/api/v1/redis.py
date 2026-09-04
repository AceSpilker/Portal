"""Redis 缓存与会话接口（M15-14；dev-plan P25.1/P25.4；api-spec §4.12）。

- GET/PUT /api/settings/redis：连接配置（密码 Fernet 加密存储，回传脱敏）；
- POST /api/redis/test：连接测试（PING + server 版本）；
- GET /api/redis/status：当前存储模式（redis/memory/redis-degraded）。

未启用时 MemoryStore 兜底，全部功能照常（自动降级/回切见 core/stores.py）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.core.i18n import t
from app.core.response import CODE_VALIDATION, BizError, ok
from app.core.secret_box import decrypt_secret, encrypt_secret
from app.core.stores import stores
from app.db.session import get_session
from app.models.setting import Setting
from app.models.user import User

router = APIRouter()

REDIS_KEYS = ("redis.host", "redis.port", "redis.password", "redis.db",
              "redis.key_prefix", "redis.enabled")


async def get_config(session: AsyncSession) -> dict:
    cfg: dict = {}
    for key in REDIS_KEYS:
        row = await session.get(Setting, key)
        cfg[key.split(".", 1)[1]] = json_loads(row.value) if row else None
    cfg["password"] = decrypt_secret(str(cfg.get("password") or ""))
    cfg["enabled"] = bool(cfg.get("enabled"))
    cfg["port"] = int(cfg.get("port") or 6379)
    cfg["db"] = int(cfg.get("db") or 0)
    cfg["key_prefix"] = str(cfg.get("key_prefix") or "portal:")
    return cfg


def json_loads(raw: str):
    import json

    return json.loads(raw)


def _mask(cfg: dict) -> dict:
    out = dict(cfg)
    out["password_set"] = bool(cfg.get("password"))
    out["password"] = ""
    return out


@router.get("/settings/redis")
async def get_redis_config(
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    """Redis 连接配置（密码脱敏）。"""
    return ok(_mask(await get_config(session)))


@router.put("/settings/redis")
async def put_redis_config(
    body: dict, _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    """保存配置；password 空=保持原值。保存后立即按新配置重连。"""
    mapping = {
        "host": str(body.get("host", ""))[:253],
        "port": int(body.get("port") or 6379),
        "db": max(0, int(body.get("db") or 0)),
        "key_prefix": str(body.get("key_prefix", "portal:"))[:32],
        "enabled": bool(body.get("enabled", False)),
    }
    password = str(body.get("password", ""))
    for suffix, value in mapping.items():
        await session.merge(Setting(key=f"redis.{suffix}", value=json_dumps(value)))
    if password:
        await session.merge(
            Setting(key="redis.password", value=json_dumps(encrypt_secret(password)))
        )
    await session.commit()

    cfg = await get_config(session)
    if cfg["enabled"] and cfg["host"]:
        connected = await stores.configure_redis(
            cfg["host"], cfg["port"], cfg["password"], cfg["db"], cfg["key_prefix"]
        )
        if not connected:
            raise BizError(CODE_VALIDATION, t("err.redis_unreachable"), 422)
    else:
        stores.configure_memory()
    return ok(_mask(await get_config(session)), t("ok.saved"))


def json_dumps(value):
    import json

    return json.dumps(value)


@router.post("/redis/test")
async def redis_test(
    body: dict | None = None,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """连接测试（P25.1）：body 传配置则用传入值（未保存前测试），否则用已存配置。"""
    body = body or {}
    cfg = await get_config(session)
    if body.get("host"):
        cfg.update(
            {
                "host": str(body.get("host", cfg["host"])),
                "port": int(body.get("port") or cfg["port"]),
                "password": str(body.get("password", "")) or cfg["password"],
                "db": int(body.get("db") or cfg["db"]),
            }
        )
    if not cfg["host"]:
        raise BizError(CODE_VALIDATION, t("err.redis_not_configured"), 422)
    import redis.asyncio as aioredis

    client = aioredis.Redis(
        host=cfg["host"], port=cfg["port"], password=cfg["password"] or None, db=cfg["db"],
        socket_timeout=2.0, socket_connect_timeout=2.0,
    )
    try:
        await client.ping()
        info = await client.info("server")
        version = str(info.get("redis_version", ""))
        return ok({"ok": True, "server_version": version})
    except Exception as exc:
        return ok({"ok": False, "error": str(exc)[:300]})
    finally:
        await client.aclose()


@router.get("/redis/status")
async def redis_status(_: User = Depends(require_admin)):
    """当前存储模式与健康（P25.4）。"""
    return ok(stores.view())
