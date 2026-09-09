"""同步/连接事件日志查询（088）：MySQL 与 Redis 共用，管理员可见。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.core.response import ok
from app.db.session import get_session
from app.models.sync import SyncLog
from app.models.user import User

router = APIRouter()


@router.get("/sync-logs")
async def list_sync_logs(
    kind: str = Query("", description="mysql / redis，空=全部"),
    limit: int = Query(30, ge=1, le=200),
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """最近同步/连接事件（时间倒序）。"""
    conds = []
    if kind in ("mysql", "redis"):
        conds.append(SyncLog.kind == kind)
    rows = (
        (
            await session.execute(
                select(SyncLog)
                .where(*conds)
                .order_by(SyncLog.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return ok(
        {
            "items": [
                {
                    "id": r.id,
                    "kind": r.kind,
                    "action": r.action,
                    "status": r.status,
                    "duration_ms": r.duration_ms,
                    "message": r.message,
                    "created_at": r.created_at.isoformat() + "Z",
                }
                for r in rows
            ]
        }
    )
