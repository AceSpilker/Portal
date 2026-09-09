"""知识库数据源模型（091）：服务器映射目录（原样读取）与 Git 仓库（克隆/拉取同步）。

- local：路径为容器内可见的映射目录（compose volumes 挂载），文件即原文件，零拷贝；
- git：克隆到 data/knowledge/{id}/（数据卷持久化），sync 时 pull，失败自动重建；
  私库凭据 username/password，password 用 Fernet 加密存储（与 MySQL 同密码盒）。
"""

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class KnowledgeSource(Base, TimestampMixin):
    __tablename__ = "knowledge_sources"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(8))  # local / git
    path: Mapped[str] = mapped_column(Text, default="")  # local=容器内目录; git=仓库 https URL
    branch: Mapped[str] = mapped_column(String(64), default="")  # git 分支（空=默认分支）
    username: Mapped[str] = mapped_column(String(64), default="")  # git 私库用户名
    password: Mapped[str] = mapped_column(Text, default="")  # git 私库密码/token（Fernet 密文）
    enabled: Mapped[bool] = mapped_column(default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    last_commit: Mapped[str] = mapped_column(String(64), default="")
    last_status: Mapped[str] = mapped_column(String(16), default="idle")  # idle/ok/failed
    last_error: Mapped[str] = mapped_column(Text, default="")
