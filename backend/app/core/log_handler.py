"""系统日志落库（072）：logging Handler 入队 + 定时任务批量写 system_logs。

- 仅落 WARNING 及以上（含定时任务异常、HTTP 500 堆栈），启动/停止等关键 INFO 白名单放行；
  uvicorn.access 等高频 INFO 不入库，防表膨胀；
- emit 永不抛错、队列满即丢弃，日志系统自身故障不能影响业务；
- 刷库走 APScheduler 任务（flush_system_logs，与现有任务同模式、随调度器干净收场），
  不用常驻后台协程——实测其在 TestClient 关闭时会孤儿化 aiosqlite 连接导致退出挂起。
"""

from __future__ import annotations

import logging
import queue
from datetime import datetime, timedelta

from app.db.session import SessionLocal
from app.models.system_log import SystemLog

_QUEUE: queue.Queue[tuple[str, str, str, datetime]] = queue.Queue(maxsize=2000)

# 启动/停止等关键 INFO 白名单（子串匹配 message）
_STARTUP_MARKERS = (
    "Started server process",
    "Application startup complete",
    "Uvicorn running on",
    "Finished server process",
    "Waiting for application shutdown",
    "Application shutdown complete",
)


class SystemLogHandler(logging.Handler):
    """WARNING+ 与启动类 INFO 入队；格式化失败静默丢弃。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.levelno < logging.WARNING and not any(
                s in record.getMessage() for s in _STARTUP_MARKERS
            ):
                return
            msg = self.format(record)[:2000]
            _QUEUE.put_nowait(
                (record.levelname, record.name, msg, datetime.utcfromtimestamp(record.created))
            )
        except Exception:  # noqa: S110 日志入队失败必须静默
            pass


def attach_system_log_handler() -> SystemLogHandler:
    """挂到根 logger（uvicorn/app 的日志统一捕获）。"""
    handler = SystemLogHandler()
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    return handler


async def flush_system_logs() -> int:
    """批量刷队列到 system_logs（APScheduler 每 10s 调用），返回本批条数。"""
    batch: list[tuple[str, str, str, datetime]] = []
    while not _QUEUE.empty() and len(batch) < 100:
        batch.append(_QUEUE.get_nowait())
    if not batch:
        return 0
    async with SessionLocal() as session:
        for level, logger, message, created in batch:
            session.add(
                SystemLog(level=level, logger=logger, message=message, created_at=created)
            )
        await session.commit()
    return len(batch)


async def cleanup_system_logs(days: int = 30) -> int:
    """删除 N 天前的系统日志（每日定时调用），返回删除条数。"""
    from sqlalchemy import delete, select

    cutoff = datetime.utcnow() - timedelta(days=days)
    async with SessionLocal() as session:
        total = (
            await session.execute(select(SystemLog.id).where(SystemLog.created_at < cutoff))
        ).all()
        if not total:
            return 0
        await session.execute(delete(SystemLog).where(SystemLog.created_at < cutoff))
        await session.commit()
        return len(total)
