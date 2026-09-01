"""系统健康检查（api-spec 4.12；dev-plan P0.2/P1）。

公开访问；附带 initialized 标志供前端判断是否进入初始化向导。
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ok
from app.db.session import get_session
from app.models.user import User

router = APIRouter()


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    users_total = await session.scalar(select(func.count()).select_from(User))
    return ok(
        {
            "status": "ok",
            "app": "portal",
            "version": "0.1.0",
            "initialized": (users_total or 0) > 0,
        }
    )
