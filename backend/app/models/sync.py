"""MySQL 镜像同步状态模型（M15-12；dev-plan P23；api-spec §3 sync_state）。"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SyncState(Base, TimestampMixin):
    """每表同步状态（api-spec §3）：最近推送/行数/结果与退避重试线索。"""

    __tablename__ = "sync_state"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    table_name: Mapped[str] = mapped_column(String(64), unique=True)
    last_push_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    last_try_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    rows_pushed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="idle")  # idle/running/ok/failed
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
