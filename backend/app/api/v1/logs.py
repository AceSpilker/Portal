"""系统日志查询（072）：system_logs 分页筛选（管理员）。"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.core.response import ok
from app.db.session import get_session
from app.models.system_log import SystemLog

router = APIRouter()

_RANGES = {"24h": 1, "7d": 7, "30d": 30, "all": None}


@router.get("/system-logs")
async def list_system_logs(
    level: str = "",
    q: str = "",
    range_: str = Query("7d", alias="range"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _: object = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """系统运行日志分页查询（WARNING+ 与启动类 INFO）。"""
    days = _RANGES.get(range_)
    if days is None and range_ != "all":
        days = 7
    conds = []
    if days is not None:
        conds.append(SystemLog.created_at >= datetime.utcnow() - timedelta(days=days))
    if level:
        conds.append(SystemLog.level == level)
    if q:
        conds.append(SystemLog.message.like(f"%{q}%"))
    total = (
        await session.execute(select(func.count()).select_from(SystemLog).where(*conds))
    ).scalar() or 0
    rows = (
        (
            await session.execute(
                select(SystemLog)
                .where(*conds)
                .order_by(SystemLog.id.desc())
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
                    "level": r.level,
                    "logger": r.logger,
                    "message": r.message,
                    "created_at": r.created_at.isoformat() + "Z",
                }
                for r in rows
            ],
        }
    )
