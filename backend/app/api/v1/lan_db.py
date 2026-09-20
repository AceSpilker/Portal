"""局域网数据库服务接口（M20；dev-plan P27.1~P27.6；api-spec §4.15）。

- /api/lan/db/scan|services：指纹扫描与服务清单（清单 A，联动标注所属设备）；
- /api/lan/db/credentials：凭据 CRUD 与连接测试（M；secret Fernet 加密、脱敏回传）；
- /api/lan/db/{mysql|redis|minio}/{sid}/*：只读查看器端点（M；白名单固定视图，
  全部为服务端固定查询，无任意 SQL/命令输入；目标限私网 4006）；
- 服务联动：一键建端口监控项（M18）。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_admin
from app.core.i18n import t
from app.core.response import (
    CODE_CIDR_FORBIDDEN,
    CODE_DUPLICATED,
    CODE_NOT_FOUND,
    CODE_SCAN_BUSY,
    CODE_TARGET_UNREACHABLE,
    CODE_VALIDATION,
    BizError,
    ok,
)
from app.core.secret_box import encrypt_secret
from app.db.session import get_session
from app.models.lan import DbCredential, LanDbService, LanDevice
from app.models.port import PortMonitor
from app.models.user import User
from app.services import db_fingerprint, db_viewers
from app.services.audit import client_ip, write_audit
from app.services.db_viewers import ViewerError

router = APIRouter()

_CRED_TYPES = ("mysql", "redis", "minio")


async def db_probe_job() -> None:
    """调度任务（P27.6，每 120s）：已发现数据库服务探活，翻转走通知 + WS。"""
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        await db_fingerprint.probe_due_services(session)


# ---- 扫描与清单 ----

@router.post("/lan/db/scan")
async def post_db_scan(
    request: Request, body: dict | None = None,
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    """触发数据库端口指纹扫描（与设备扫描共用互斥位）。"""
    body = body or {}
    cidrs = [str(c)[:64] for c in (body.get("cidrs") or [])]
    try:
        from app.api.v1.lan import _hint_ips

        run = await db_fingerprint.start_db_scan(
            session, cidrs or None, hint_ips=_hint_ips(request)
        )
    except LookupError as exc:
        raise BizError(CODE_SCAN_BUSY, t("err.lan_scan_busy"), 409) from exc
    except ValueError as exc:
        raise BizError(
            CODE_CIDR_FORBIDDEN, t("err.lan_cidr_invalid", cidr=str(exc)[:120]), 422
        ) from exc
    await write_audit(
        session, _.id, "lan_db_scan", f"cidrs={json.loads(run.cidrs)}", client_ip(request)
    )
    await session.commit()
    return ok({"run_id": run.id, "cidrs": json.loads(run.cidrs)})


@router.get("/lan/db/services")
async def list_services(
    type: str = "",
    _: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
):
    """服务清单：类型/版本/凭据状态/探活 + 所属设备标注（联动 M19）。"""
    rows = (await session.execute(select(LanDbService))).scalars().all()
    devices = {d.ip: d for d in (await session.execute(select(LanDevice))).scalars().all()}
    items = []
    for s in rows:
        if type and s.service_type != type:
            continue
        dev = devices.get(s.host)
        items.append({
            "id": s.id, "host": s.host, "port": s.port, "service_type": s.service_type,
            "version": s.version, "state": s.state, "latency_ms": s.latency_ms,
            "credential_id": s.credential_id, "online": bool(s.online),
            "first_seen_at": s.first_seen_at, "last_seen_at": s.last_seen_at,
            "device": {
                "id": dev.id, "hostname": dev.hostname, "device_type": dev.device_type,
            } if dev else None,
        })
    items.sort(key=lambda i: (i["service_type"] == "unknown", i["service_type"], i["host"]))
    return ok({"items": items, "total": len(items)})


@router.post("/lan/db/services/{sid}/monitor")
async def service_create_monitor(
    sid: int, request: Request,
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    svc = await session.get(LanDbService, sid)
    if svc is None:
        raise BizError(CODE_NOT_FOUND, t("err.db_service_not_found"), 404)
    dup = (
        await session.execute(
            select(PortMonitor).where(PortMonitor.host == svc.host, PortMonitor.port == svc.port)
        )
    ).scalar_one_or_none()
    if dup:
        raise BizError(CODE_DUPLICATED, t("err.already_exists", name=f"{svc.host}:{svc.port}"), 409)
    m = PortMonitor(
        name=f"{svc.service_type}:{svc.host}", host=svc.host, port=svc.port, interval=60, enabled=1,
    )
    session.add(m)
    await write_audit(session, _.id, "lan_db_monitor", f"{svc.host}:{svc.port}", client_ip(request))
    await session.commit()
    return ok({"id": m.id})


# ---- 凭据管理 ----

def _cred_view(c: DbCredential) -> dict:
    return {
        "id": c.id, "name": c.name, "service_type": c.service_type,
        "host": c.host, "port": c.port, "username": c.username,
        "password_set": bool(c.secret), "extra": json.loads(c.extra or "{}"),
        "enabled": bool(c.enabled), "last_test_at": c.last_test_at,
        "last_test_ok": None if c.last_test_ok is None else bool(c.last_test_ok),
    }


async def _get_cred_or_404(session: AsyncSession, cred_id: int) -> DbCredential:
    cred = await session.get(DbCredential, cred_id)
    if cred is None:
        raise BizError(CODE_NOT_FOUND, t("err.db_credential_not_found"), 404)
    return cred


def _ensure_private(host: str) -> None:
    from app.services.lan_scan import is_private_ip

    if not is_private_ip(host):
        raise BizError(CODE_CIDR_FORBIDDEN, t("err.lan_target_forbidden"), 422)


@router.get("/lan/db/credentials")
async def list_credentials(
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(select(DbCredential).order_by(DbCredential.id))
    ).scalars().all()
    return ok({"items": [_cred_view(c) for c in rows], "total": len(rows)})


@router.post("/lan/db/credentials")
async def create_credential(
    body: dict, _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    stype = str(body.get("service_type") or "")
    if stype not in _CRED_TYPES:
        raise BizError(CODE_VALIDATION, t("v.invalid", field="service_type"), 422)
    host = str(body.get("host") or "").strip()
    port = int(body.get("port") or 0)
    if not host or not (1 <= port <= 65535):
        raise BizError(CODE_VALIDATION, t("v.invalid", field="host:port"), 422)
    _ensure_private(host)
    dup = (
        await session.execute(
            select(DbCredential).where(DbCredential.host == host, DbCredential.port == port)
        )
    ).scalar_one_or_none()
    if dup:
        raise BizError(CODE_DUPLICATED, t("err.db_credential_dup"), 409)
    cred = DbCredential(
        name=str(body.get("name") or f"{stype} {host}:{port}")[:64],
        service_type=stype, host=host, port=port,
        username=str(body.get("username") or "")[:128],
        secret=encrypt_secret(str(body.get("password") or "")),
        extra=json.dumps(_norm_extra(stype, body.get("extra"))),
        enabled=1 if body.get("enabled", True) else 0,
    )
    session.add(cred)
    await session.commit()
    await _link_service(session, cred)
    return ok(_cred_view(cred))


def _norm_extra(stype: str, extra: dict | None) -> dict:
    extra = extra or {}
    out: dict = {}
    if stype == "mysql" and extra.get("database"):
        out["database"] = str(extra["database"])[:64]
    if stype == "redis":
        try:
            out["db"] = max(0, min(15, int(extra.get("db") or 0)))
        except (TypeError, ValueError):
            out["db"] = 0
    if stype == "minio":
        out["use_ssl"] = bool(extra.get("use_ssl", False))
        if extra.get("region"):
            out["region"] = str(extra["region"])[:32]
    return out


async def _link_service(session: AsyncSession, cred: DbCredential) -> None:
    """凭据按 host:port 自动关联已发现的服务。"""
    svc = (
        await session.execute(
            select(LanDbService).where(
                LanDbService.host == cred.host, LanDbService.port == cred.port
            )
        )
    ).scalar_one_or_none()
    if svc and svc.credential_id is None:
        svc.credential_id = cred.id
        await session.commit()


@router.put("/lan/db/credentials/{cred_id}")
async def update_credential(
    cred_id: int, body: dict,
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    cred = await _get_cred_or_404(session, cred_id)
    if body.get("name") is not None:
        cred.name = str(body["name"])[:64]
    if body.get("username") is not None:
        cred.username = str(body["username"])[:128]
    if body.get("password"):
        cred.secret = encrypt_secret(str(body["password"]))
    if body.get("enabled") is not None:
        cred.enabled = 1 if body["enabled"] else 0
    if body.get("extra") is not None:
        cred.extra = json.dumps(_norm_extra(cred.service_type, body.get("extra")))
    await session.commit()
    await _link_service(session, cred)
    return ok(_cred_view(cred))


@router.delete("/lan/db/credentials/{cred_id}")
async def delete_credential(
    cred_id: int, _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    cred = await _get_cred_or_404(session, cred_id)
    services = (
        await session.execute(select(LanDbService).where(LanDbService.credential_id == cred_id))
    ).scalars().all()
    for svc in services:  # 解除关联后允许删除（服务保留，仅凭据状态归零）
        svc.credential_id = None
    await session.delete(cred)
    await session.commit()
    return ok(None, t("ok.deleted"))


@router.post("/lan/db/credentials/{cred_id}/test")
async def test_credential(
    cred_id: int, _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    """连接测试：真实握手（MySQL SELECT 1 / Redis PING+INFO / MinIO ListBuckets）。"""
    from datetime import datetime

    cred = await _get_cred_or_404(session, cred_id)
    result = await db_viewers.test_credential(cred)
    cred.last_test_at = datetime.utcnow()
    cred.last_test_ok = 1 if result["ok"] else 0
    await session.commit()
    return ok(result)


# ---- 查看器（只读；M） ----

async def _viewer_service(session: AsyncSession, sid: int) -> LanDbService:
    svc = await session.get(LanDbService, sid)
    if svc is None:
        raise BizError(CODE_NOT_FOUND, t("err.db_service_not_found"), 404)
    return svc


async def _viewer_cred(session: AsyncSession, svc: LanDbService) -> DbCredential:
    cred = svc.credential_id and await session.get(DbCredential, svc.credential_id)
    if cred is None:
        cred = (
            await session.execute(
                select(DbCredential).where(
                    DbCredential.host == svc.host, DbCredential.port == svc.port,
                    DbCredential.enabled == 1,
                )
            )
        ).scalar_one_or_none()
    if cred is None:
        msg = t("err.db_credential_not_found") + f"（{svc.host}:{svc.port}）"
        raise BizError(CODE_VALIDATION, msg, 422)
    return cred


def _viewer_error(exc: ViewerError) -> BizError:
    return BizError(CODE_TARGET_UNREACHABLE, str(exc))


def _audit_view(
    user: User, session: AsyncSession, request: Request, action: str, detail: str
) -> None:
    write_audit(session, user.id, action, detail, client_ip(request))


# —— MySQL ——

@router.get("/lan/db/mysql/{sid}/overview")
async def mysql_overview(
    sid: int, request: Request,
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    svc = await _viewer_service(session, sid)
    cred = await _viewer_cred(session, svc)
    try:
        data = await db_viewers.mysql_overview(cred)
    except ViewerError as exc:
        raise _viewer_error(exc) from exc
    _audit_view(_, session, request, "db_view", f"mysql {svc.host}:{svc.port} overview")
    await session.commit()
    return ok(data)


@router.get("/lan/db/mysql/{sid}/variables")
async def mysql_variables(
    sid: int, request: Request, q: str = "",
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    svc = await _viewer_service(session, sid)
    cred = await _viewer_cred(session, svc)
    try:
        data = await db_viewers.mysql_variables(cred, q)
    except ViewerError as exc:
        raise _viewer_error(exc) from exc
    return ok(data)


@router.get("/lan/db/mysql/{sid}/schemas")
async def mysql_schemas(
    sid: int, request: Request, schema: str = "", page: int = 1, page_size: int = 50,
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    svc = await _viewer_service(session, sid)
    cred = await _viewer_cred(session, svc)
    try:
        data = await db_viewers.mysql_schemas(
            cred, schema, max(1, page), max(1, min(200, page_size))
        )
    except ViewerError as exc:
        raise _viewer_error(exc) from exc
    return ok(data)


@router.get("/lan/db/mysql/{sid}/processlist")
async def mysql_processlist(
    sid: int, request: Request,
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    svc = await _viewer_service(session, sid)
    cred = await _viewer_cred(session, svc)
    try:
        data = await db_viewers.mysql_processlist(cred)
    except ViewerError as exc:
        raise _viewer_error(exc) from exc
    return ok(data)


# —— Redis ——

@router.get("/lan/db/redis/{sid}/info")
async def redis_info(
    sid: int, request: Request,
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    svc = await _viewer_service(session, sid)
    cred = await _viewer_cred(session, svc)
    try:
        data = await db_viewers.redis_info(cred)
    except ViewerError as exc:
        raise _viewer_error(exc) from exc
    _audit_view(_, session, request, "db_view", f"redis {svc.host}:{svc.port} info")
    await session.commit()
    return ok(data)


@router.get("/lan/db/redis/{sid}/keys")
async def redis_keys(
    sid: int, request: Request, db: int = 0, cursor: int = 0, match: str = "",
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    svc = await _viewer_service(session, sid)
    cred = await _viewer_cred(session, svc)
    try:
        data = await db_viewers.redis_keys(
            cred, max(0, min(15, db)), cursor, match[:128], 100
        )
    except ViewerError as exc:
        raise _viewer_error(exc) from exc
    return ok(data)


@router.get("/lan/db/redis/{sid}/key")
async def redis_key_detail(
    sid: int, request: Request, key: str, db: int = 0,
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    svc = await _viewer_service(session, sid)
    cred = await _viewer_cred(session, svc)
    if not key:
        raise BizError(CODE_VALIDATION, t("v.missing", field="key"), 422)
    try:
        data = await db_viewers.redis_key_detail(cred, key[:512], max(0, min(15, db)))
    except ViewerError as exc:
        raise _viewer_error(exc) from exc
    return ok(data)


@router.get("/lan/db/redis/{sid}/slowlog")
async def redis_slowlog(
    sid: int, request: Request,
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    svc = await _viewer_service(session, sid)
    cred = await _viewer_cred(session, svc)
    try:
        data = await db_viewers.redis_slowlog(cred)
    except ViewerError as exc:
        raise _viewer_error(exc) from exc
    return ok(data)


@router.get("/lan/db/redis/{sid}/clients")
async def redis_clients(
    sid: int, request: Request,
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    svc = await _viewer_service(session, sid)
    cred = await _viewer_cred(session, svc)
    try:
        data = await db_viewers.redis_clients(cred)
    except ViewerError as exc:
        raise _viewer_error(exc) from exc
    return ok(data)


# —— MinIO ——

@router.get("/lan/db/minio/{sid}/overview")
async def minio_overview(
    sid: int, request: Request,
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    svc = await _viewer_service(session, sid)
    cred = await _viewer_cred(session, svc)
    try:
        data = await db_viewers.minio_overview(cred)
    except ViewerError as exc:
        raise _viewer_error(exc) from exc
    _audit_view(_, session, request, "db_view", f"minio {svc.host}:{svc.port} overview")
    await session.commit()
    return ok(data)


@router.get("/lan/db/minio/{sid}/buckets")
async def minio_buckets(
    sid: int, request: Request,
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    svc = await _viewer_service(session, sid)
    cred = await _viewer_cred(session, svc)
    try:
        data = await db_viewers.minio_buckets(cred)
    except ViewerError as exc:
        raise _viewer_error(exc) from exc
    return ok(data)


@router.get("/lan/db/minio/{sid}/objects")
async def minio_objects(
    sid: int, request: Request, bucket: str, prefix: str = "", token: str = "", limit: int = 100,
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    svc = await _viewer_service(session, sid)
    cred = await _viewer_cred(session, svc)
    if not bucket:
        raise BizError(CODE_VALIDATION, t("v.missing", field="bucket"), 422)
    try:
        data = await db_viewers.minio_objects(cred, bucket[:128], prefix[:512], token[:512], limit)
    except ViewerError as exc:
        raise _viewer_error(exc) from exc
    return ok(data)


@router.get("/lan/db/minio/{sid}/object-url")
async def minio_object_url(
    sid: int, request: Request, bucket: str, key: str, expires: int = 300,
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    """对象预签名下载 URL（只读 GET，短时效）。"""
    svc = await _viewer_service(session, sid)
    cred = await _viewer_cred(session, svc)
    if not bucket or not key:
        raise BizError(CODE_VALIDATION, t("v.missing", field="bucket/key"), 422)
    url = db_viewers.minio_object_url(cred, bucket[:128], key[:1024], max(60, min(3600, expires)))
    _audit_view(_, session, request, "db_view", f"minio {bucket}/{key[:80]} presign")
    await session.commit()
    return ok({"url": url, "expires_in": max(60, min(3600, expires))})
