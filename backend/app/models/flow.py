"""Flow 自动化模型（M06；dev-plan P14；api-spec §3.7）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

TRIGGER_TYPES = ("cron", "webhook", "manual", "event")


class Flow(Base):
    __tablename__ = "flows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    trigger_type: Mapped[str] = mapped_column(Text, default="manual")
    trigger_config: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    actions: Mapped[str] = mapped_column(Text, default="[]")  # JSON 动作数组（含条件节点）
    enabled: Mapped[int] = mapped_column(Integer, default=0)
    webhook_token: Mapped[str | None] = mapped_column(Text, default=None, unique=True)
    retry: Mapped[int] = mapped_column(Integer, default=0)
    retry_interval: Mapped[int] = mapped_column(Integer, default=60)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class FlowRun(Base):
    __tablename__ = "flow_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    flow_id: Mapped[int] = mapped_column(Integer)
    trigger: Mapped[str] = mapped_column(Text)  # cron/webhook/manual/event
    status: Mapped[str] = mapped_column(Text, default="running")  # running/success/failed
    steps_log: Mapped[str] = mapped_column(Text, default="[]")  # JSON 每步输入输出
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)

    __table_args__ = (Index("ix_flow_runs_flow_ts", "flow_id", "started_at"),)
