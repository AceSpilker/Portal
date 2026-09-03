"""AI 助手模型（M05-4~9；dev-plan P13；api-spec §3.9）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AiConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text, default="新对话")
    provider: Mapped[str] = mapped_column(Text, default="")  # Provider 名（快照）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AiMessage(Base):
    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(Text)  # user / assistant / system
    content: Mapped[str] = mapped_column(Text, default="")
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_ai_messages_conv", "conversation_id", "created_at"),)
