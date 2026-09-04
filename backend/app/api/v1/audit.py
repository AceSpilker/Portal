"""审计日志查询与导出（M01-14/M15-13；dev-plan P17.1；api-spec §4.12）。

数据同源 audit_logs（P7.4 起写入）；管理员可按动作/用户/时间范围筛选、
分页浏览与 CSV 导出（系统日志中心 M15-13 复用同一数据源）。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.core.response import ok
from app.db.session import get_session
from app.models.audit import AuditLog
from app.models.user import User

router = APIRouter()

_RANGES = {"24h": 1, "7d": 7, "30d": 30, "all": None}


@router.get("/audit-logs")
async def list_audit_logs(
    action: str = "",
    user_id: int | None = None,
    range_: str = Query("7d", alias="range"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """审计日志分页查询（M）。"""
    days = _RANGES.get(range_)
    if days is None and range_ != "all":
        days = 7
    conds = []
    if days is not None:
        conds.append(AuditLog.created_at >= datetime.utcnow() - timedelta(days=days))
    if action:
        conds.append(AuditLog.action == action)
    if user_id is not None:
        conds.append(AuditLog.user_id == user_id)
    total = (
        await session.execute(select(func.count()).select_from(AuditLog).where(*conds))
    ).scalar() or 0
    rows = (
        (
            await session.execute(
                select(AuditLog)
                .where(*conds)
                .order_by(AuditLog.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return ok(
        {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [
                {
                    "id": r.id,
                    "user_id": r.user_id,
                    "action": r.action,
                    "detail": r.detail,
                    "ip": r.ip,
                    "created_at": r.created_at.isoformat() + "Z",
                }
                for r in rows
            ],
        }
    )


@router.get("/audit-logs/export")
async def export_audit_logs(
    range_: str = Query("30d", alias="range"),
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """CSV 导出（M01-14/M15-13）。"""
    import csv
    import io

    days = _RANGES.get(range_)
    if days is None:
        days = 30
    rows = (
        (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.created_at >= datetime.utcnow() - timedelta(days=days))
                .order_by(AuditLog.id)
            )
        )
        .scalars()
        .all()
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "user_id", "action", "detail", "ip", "created_at"])
    for r in rows:
        writer.writerow(
            [r.id, r.user_id or "", r.action, r.detail.replace("\n", " "),
             r.ip, r.created_at.isoformat()]
        )
    return ok({"filename": f"audit-{range_}.csv", "csv": buf.getvalue()})
