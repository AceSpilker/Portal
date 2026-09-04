"""MySQL 同步接口（M15-12；dev-plan P23；api-spec §4.12）。

- GET/PUT /api/settings/sync：配置读写（密码加密存储，回传脱敏）；
- POST /api/mysql/test：连接测试；
- POST /api/sync/push · GET /api/sync/status · POST /api/sync/restore：
  立即推送 / 每表状态 / 灾难恢复（先自动备份本地）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.core.i18n import t
from app.core.response import CODE_VALIDATION, BizError, ok
from app.db.session import get_session
from app.models.user import User
from app.services import mysql_sync

router = APIRouter()


def _mask(cfg: dict) -> dict:
    out = dict(cfg)
    out["password_set"] = bool(cfg.get("password"))
    out["password"] = ""  # 永不回传
    return out


@router.get("/settings/sync")
async def get_sync_config(
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    """同步配置（密码脱敏）。"""
    return ok(_mask(await mysql_sync.get_config(session)))


@router.put("/settings/sync")
async def put_sync_config(
    body: dict, _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    """保存同步配置；password 空=保持原值，明文传入则 Fernet 加密落库。"""
    await mysql_sync.save_config(session, body)
    await session.commit()
    return ok(_mask(await mysql_sync.get_config(session)), t("ok.saved"))


@router.post("/mysql/test")
async def mysql_test(
    body: dict | None = None,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """连接测试（M23.2）：body 传配置则用传入值（未保存前测试），否则用已存配置。"""
    body = body or {}
    cfg = await mysql_sync.get_config(session)
    if body.get("host"):
        cfg.update(
            {
                "host": str(body.get("host", cfg["host"])),
                "port": int(body.get("port") or cfg["port"]),
                "user": str(body.get("user", cfg["user"])),
                "password": str(body.get("password", "")) or cfg["password"],
                "database": str(body.get("database", cfg["database"])),
            }
        )
    if not cfg["host"]:
        raise BizError(CODE_VALIDATION, t("err.mysql_not_configured"), 422)
    try:
        result = await mysql_sync.test_connection(cfg)
    except Exception as exc:
        return ok({"ok": False, "error": str(exc)[:300]})
    return ok(result)


@router.post("/sync/push")
async def sync_push(
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    """立即推送（M23.3）：force 忽略退避。"""
    result = await mysql_sync.push_all(session, force=True)
    return ok(result)


@router.get("/sync/status")
async def sync_status(
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    """每表同步状态（M23.4）。"""
    return ok(await mysql_sync.sync_status(session))


@router.post("/sync/restore")
async def sync_restore(
    body: dict = None,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """从 MySQL 恢复到 SQLite（M23.5）：先自动备份本地；需 confirm=true。"""
    if not (body or {}).get("confirm"):
        raise BizError(CODE_VALIDATION, t("err.restore_confirm_required"), 422)
    from app.services.backup import write_disk_backup

    backup = await write_disk_backup(session)
    try:
        counts = await mysql_sync.restore_from_mysql(session)
    except Exception as exc:
        return ok({"ok": False, "backup": backup.name, "error": str(exc)[:300]})
    return ok({"ok": True, "backup": backup.name, **counts}, t("ok.restored"))
