"""审计日志模型（M01-14；api-spec §3.1 audit_logs）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, default=None)
    action: Mapped[str] = mapped_column(Text)  # login/update_config/user_create/…
    detail: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # ---- 087 请求执行详情（中间件自动审计写入；手动业务审计为空串/0）----
    method: Mapped[str] = mapped_column(Text, default="")  # POST/PUT/PATCH/DELETE
    path: Mapped[str] = mapped_column(Text, default="")  # /api/xxx 接口路径
    query: Mapped[str] = mapped_column(Text, default="")  # 查询串（不含 ?）
    status: Mapped[int] = mapped_column(Integer, default=0)  # HTTP 状态码
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)  # 执行耗时
    user_agent: Mapped[str] = mapped_column(Text, default="")
    error_msg: Mapped[str] = mapped_column(Text, default="")  # >=400 时统一响应的 message
