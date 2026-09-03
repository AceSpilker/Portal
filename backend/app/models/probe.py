"""探活状态模型（M07-2；api-spec §3.4 app_status / probe_events）。

notifications（api-spec §3.8 标注 M2）因 P6.4 需要提前建表写入，
列表/已读等完整能力仍在 P9 交付。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AppStatus(Base):
    __tablename__ = "app_status"

    app_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    state: Mapped[str] = mapped_column(Text, default="unknown")  # up / down / unknown
    latency_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    since: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)  # 当前状态起始
    message: Mapped[str | None] = mapped_column(Text, default="")


class ProbeEvent(Base):
    __tablename__ = "probe_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    app_id: Mapped[int] = mapped_column(Integer)
    event: Mapped[str] = mapped_column(Text)  # up / down / slow
    latency_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_probe_events_app_created", "app_id", "created_at"),)


class UrlProbeSample(Base):
    """入口延迟采样（M04-14；dev-plan P15.4）：每次入口探测记录一条，供趋势图。

    定时任务每 5min 全量探测一轮；点击前预检（/apps/{id}/precheck）与
    连通性矩阵（/connectivity/matrix）的结果也写入；保留 7 天。
    """

    __tablename__ = "url_probe_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url_id: Mapped[int] = mapped_column(Integer, index=True)
    app_id: Mapped[int] = mapped_column(Integer, index=True)  # 冗余：URL 删除后按应用清理
    state: Mapped[str] = mapped_column(Text, default="unknown")  # up / down / unknown
    latency_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, default="")
    level: Mapped[str] = mapped_column(Text, default="info")  # info / warn / error
    source: Mapped[str] = mapped_column(Text, default="probe")  # probe/metric/port/flow/system
    is_read: Mapped[int] = mapped_column(Integer, default=0)
    dedup_key: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
