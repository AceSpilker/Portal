"""SSH 托管隧道模型（M04-16；dev-plan P20.1/P20.2；api-spec §3.6）。

凭据 secret/private_key 用 data/keys/sync.key（Fernet）加密存储，只回掩码。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SSHCredential(Base, TimestampMixin):
    """SSH 凭据（密码 / 私钥二选一）。"""

    __tablename__ = "ssh_credentials"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text)
    host: Mapped[str] = mapped_column(Text)
    port: Mapped[int] = mapped_column(Integer, default=22)
    username: Mapped[str] = mapped_column(Text, default="root")
    secret: Mapped[str] = mapped_column(Text, default="", server_default="")  # Fernet 密文
    note: Mapped[str] = mapped_column(Text, default="", server_default="")


class Tunnel(Base, TimestampMixin):
    """SSH 本地端口转发隧道：本机 local_port →（经 SSH 服务器）→ remote_host:remote_port。

    status: stopped / running / error / degraded(断线重连中)。
    """

    __tablename__ = "tunnels"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text)
    credential_id: Mapped[int] = mapped_column(
        ForeignKey("ssh_credentials.id", ondelete="CASCADE"), index=True
    )
    remote_host: Mapped[str] = mapped_column(Text, default="127.0.0.1")
    remote_port: Mapped[int] = mapped_column(Integer)
    local_port: Mapped[int] = mapped_column(Integer, default=0)  # 0=自动分配
    auto_close_min: Mapped[int] = mapped_column(Integer, default=30)  # 空闲回收（分钟，0=不回收）
    status: Mapped[str] = mapped_column(Text, default="stopped")
    last_error: Mapped[str] = mapped_column(Text, default="")
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    desired: Mapped[int] = mapped_column(Integer, default=0)  # 期望运行态（重连判定用）
