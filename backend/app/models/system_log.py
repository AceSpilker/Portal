"""系统运行日志模型（072；用户诉求：应用内可查日志信息）。

由 app/core/log_handler.py 的 SystemLogHandler 落库：WARNING 及以上自动记录
（含定时任务异常、HTTP 500 堆栈），启动/停止等关键 INFO 白名单放行；
uvicorn.access 等高频 INFO 不入库，防表膨胀。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SystemLog(Base):
    __tablename__ = "system_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(Text)  # WARNING / ERROR / INFO(仅启动类)
    logger: Mapped[str] = mapped_column(Text, default="")
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
