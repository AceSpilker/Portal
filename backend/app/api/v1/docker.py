"""Docker 容器管理接口（M08-1~4；dev-plan P12；api-spec §4.6）。

可选模块（settings.docker_sock_enabled）：未启用/sock 不可达 → 503，
前端据 GET /docker/status 隐藏模块；生命周期操作写审计日志（M08-2）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.core.deps import get_current_user, require_admin
from app.core.i18n import t
from app.core.response import BizError, ok
from app.db.session import get_session
from app.models.user import User
from app.services import docker_svc
from app.services.audit import client_ip, write_audit

router = APIRouter()


def _ensure_enabled() -> None:
    if not docker_svc.enabled():
        raise BizError(503, t("err.docker_disabled"), 503)


@router.get("/docker/status")
async def docker_status(_: User = Depends(get_current_user)):
    """模块开关（前端导航动态显示）。"""
    return ok({"enabled": docker_svc.enabled()})


@router.get("/docker/containers")
async def list_containers(_: User = Depends(require_admin)):
    _ensure_enabled()
    return ok(await docker_svc.list_containers())


@router.post("/docker/containers/{name}/{op}")
async def container_operation(
    name: str,
    op: str,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """启动/停止/重启（M08-2）：写审计日志。"""
    _ensure_enabled()
    if op not in ("start", "stop", "restart"):
        raise BizError(400, t("err.docker_bad_op"), 400)
    try:
        result = await docker_svc.container_op(name, op)
    except KeyError:
        raise BizError(404, t("err.docker_not_found"), 404)
    await write_audit(
        session,
        admin.id,
        "docker_op",
        f"容器 {name} 执行 {op}",
        client_ip(request),
    )
    await session.commit()
    return ok(result)


@router.get("/docker/containers/{name}/logs")
async def container_logs(
    name: str,
    tail: int = Query(200, ge=1, le=1000),
    _: User = Depends(require_admin),
):
    """尾部日志（M08-3）。"""
    _ensure_enabled()
    try:
        return ok({"logs": await docker_svc.container_logs(name, tail)})
    except KeyError:
        raise BizError(404, t("err.docker_not_found"), 404)


@router.get("/docker/containers/{name}/detail")
async def container_detail(
    name: str,
    _: User = Depends(require_admin),
):
    """容器详情（M08-4）：端口/卷/环境变量（脱敏）。"""
    _ensure_enabled()
    try:
        return ok(await docker_svc.container_detail(name))
    except KeyError:
        raise BizError(404, t("err.docker_not_found"), 404)
