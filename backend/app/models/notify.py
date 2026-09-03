"""通知渠道与路由规则（M09-4~12；dev-plan P9.1/P9.3；api-spec §3.8）。

- notify_channels：type 枚举 bark/telegram/smtp/webhook/wecom/dingtalk/feishu/ntfy；
  config 为 JSON，敏感字段回传时脱敏（见 api/v1/notify.py）；
- notify_rules：事件 → 渠道路由；quiet_start/quiet_end 规则级免打扰（HH:MM，可跨午夜）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

CHANNEL_TYPES = ("bark", "telegram", "smtp", "webhook", "wecom", "dingtalk", "feishu", "ntfy")
NOTIFY_EVENTS = (
    "app_down",
    "app_up",
    "metric_alert",
    "port_down",
    "port_up",
    "flow_failed",
    "system",
)


class NotifyChannel(Base):
    __tablename__ = "notify_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(Text, default="webhook")
    name: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[str] = mapped_column(Text, default="{}")  # JSON；敏感字段回传脱敏
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class NotifyRule(Base):
    __tablename__ = "notify_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event: Mapped[str] = mapped_column(Text, default="system")
    channel_ids: Mapped[str] = mapped_column(Text, default="[]")  # JSON 数组
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    quiet_start: Mapped[str | None] = mapped_column(Text, default=None)  # HH:MM
    quiet_end: Mapped[str | None] = mapped_column(Text, default=None)  # HH:MM
