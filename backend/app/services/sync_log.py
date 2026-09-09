"""同步/连接事件日志服务（088）：MySQL 推送与 Redis 连接共用的历史记录。

- record：独立 Session 写入并清理超量（每 kind 保留最近 KEEP 条），
  失败静默——日志绝不影响业务主流程；
- fire：事件现场触发（asyncio task 旁路），不阻塞当前操作。
"""

from __future__ import annotations

import asyncio

from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models.sync import SyncLog

KEEP = 200
_MSG_MAX = 400


async def record(
    kind: str, action: str, status: str, message: str = "", duration_ms: int = 0
) -> None:
    try:
        async with SessionLocal() as session:
            session.add(
                SyncLog(
                    kind=kind,
                    action=action,
                    status=status,
                    duration_ms=int(duration_ms),
                    message=str(message)[:_MSG_MAX],
                )
            )
            await session.commit()
            # 每 kind 只保留最近 KEEP 条
            stale = (
                (
                    await session.execute(
                        select(SyncLog.id)
                        .where(SyncLog.kind == kind)
                        .order_by(SyncLog.id.desc())
                        .offset(KEEP)
                    )
                )
                .scalars()
                .all()
            )
            if stale:
                await session.execute(delete(SyncLog).where(SyncLog.id.in_(stale)))
                await session.commit()
    except Exception:  # noqa: S110 日志失败静默，不影响业务
        pass


def fire(
    kind: str, action: str, status: str, message: str = "", duration_ms: int = 0
) -> None:
    """事件现场触发；无运行中事件循环时静默放弃。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(record(kind, action, status, message, duration_ms))
