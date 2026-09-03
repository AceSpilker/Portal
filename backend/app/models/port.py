"""端口监控模型（M18-1~5；dev-plan P11；api-spec §3.5）。

port_monitors：host:port 探活监控项（可关联门户应用）；
port_events：通断事件流水（翻转才记录）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PortMonitor(Base):
    __tablename__ = "port_monitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, default="")
    host: Mapped[str] = mapped_column(Text, default="127.0.0.1")
    port: Mapped[int] = mapped_column(Integer)
    app_id: Mapped[int | None] = mapped_column(Integer, default=None)  # 与门户应用关联
    interval: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(Text, default="unknown")  # up/down/unknown
    last_latency_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class PortEvent(Base):
    __tablename__ = "port_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    monitor_id: Mapped[int] = mapped_column(Integer)
    event: Mapped[str] = mapped_column(Text)  # up / down
    latency_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_port_events_monitor_ts", "monitor_id", "created_at"),)
