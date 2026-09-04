"""用户模型（M01；api-spec §3.1 users）。"""

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), default="user")  # admin / user
    is_active: Mapped[bool] = mapped_column(default=True)
    totp_secret: Mapped[str | None] = mapped_column(String(64), default=None)  # P17.1 启用
    totp_enabled: Mapped[bool] = mapped_column(default=False, server_default="0")  # P17.1
    # 恢复码 SHA-256 列表（JSON）
    totp_recovery: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    prefs: Mapped[str] = mapped_column(String(1024), default="{}")  # JSON 个人偏好
    remark: Mapped[str] = mapped_column(Text, default="", server_default="")  # 管理员备注（M01-11）
    # 密码修改时间（审计用）；token_version 早于当前版本的 token 一律失效（改密踢会话）
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    token_version: Mapped[int] = mapped_column(default=0)
