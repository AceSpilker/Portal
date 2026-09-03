"""审计日志共享服务（M01-14；P12 起 Docker 等模块共用）。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.models.audit import AuditLog


async def write_audit(
    session: AsyncSession,
    user_id: int | None,
    action: str,
    detail: str,
    request_ip: str = "",
) -> None:
    session.add(AuditLog(user_id=user_id, action=action, detail=detail, ip=request_ip))


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    return xff.split(",")[0].strip() if xff else (request.client.host if request.client else "")
