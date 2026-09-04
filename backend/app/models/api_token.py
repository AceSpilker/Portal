"""会话与开放 API Token 模型（M01-8/M14-1；dev-plan P17.1/P17.2）。"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class UserSession(Base, TimestampMixin):
    """登录会话清单（M01-8）：登录设备/会话管理/强制下线的载体。

    jti 为 refresh token 的唯一 ID；吊销后该会话 refresh 失效
    （access token 短时效，自然过期）。
    """

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True)
    device: Mapped[str] = mapped_column(Text, default="")  # User-Agent 截断
    ip: Mapped[str] = mapped_column(String(64), default="")
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class ApiToken(Base, TimestampMixin):
    """开放 API Token（M14-1）：plt_ 前缀，SHA-256 哈希存储，只读/读写两档。"""

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_prefix: Mapped[str] = mapped_column(String(12), default="")  # 展示用前 8 位
    scope: Mapped[str] = mapped_column(String(8), default="ro")  # ro / rw
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    note: Mapped[str] = mapped_column(Text, default="")
