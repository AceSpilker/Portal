"""用户模型（M01；api-spec §3.1 users）。"""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), default="user")  # admin / user
    is_active: Mapped[bool] = mapped_column(default=True)
    totp_secret: Mapped[str | None] = mapped_column(String(64), default=None)  # M2 启用
    prefs: Mapped[str] = mapped_column(String(1024), default="{}")  # JSON 个人偏好
    # 密码修改时间（审计用）；token_version 早于当前版本的 token 一律失效（改密踢会话）
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    token_version: Mapped[int] = mapped_column(default=0)
