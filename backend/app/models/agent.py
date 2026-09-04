"""多机纳管 Agent 模型（M17-18；dev-plan P21.3）。"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AgentNode(Base, TimestampMixin):
    """被纳管节点：轻量 Agent 定期上报最新指标（覆盖式，保留最近快照）。"""

    __tablename__ = "agent_nodes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    hostname: Mapped[str] = mapped_column(Text, unique=True)
    token_hash: Mapped[str] = mapped_column(Text)  # SHA-256(上报 token)
    cpu_pct: Mapped[float] = mapped_column(default=0)
    mem_pct: Mapped[float] = mapped_column(default=0)
    disk_pct: Mapped[float] = mapped_column(default=0)
    uptime_s: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[str] = mapped_column(Text, default="")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
