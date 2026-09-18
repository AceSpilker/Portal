"""局域网发现模型（M19/M20；dev-plan P26/P27；api-spec §3.12）。

lan_devices：以 IP 为主键语义的设备清单（TCP+ARP+UPnP+SNMP 多来源融合）；
lan_scan_runs：每次网段扫描的运行记录（同一时刻仅一条 running）；
lan_device_events：设备上线/下线事件流水；
lan_db_services：数据库服务指纹发现结果（host:port 唯一）；
db_credentials：数据库连接凭据（secret Fernet 加密存储，SSH 凭据同范式）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class LanDevice(Base):
    __tablename__ = "lan_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip: Mapped[str] = mapped_column(Text, unique=True)
    mac: Mapped[str | None] = mapped_column(Text, default=None)  # 冒号小写规范格式
    hostname: Mapped[str | None] = mapped_column(Text, default=None)
    vendor: Mapped[str | None] = mapped_column(Text, default=None)  # MAC OUI 厂商
    device_type: Mapped[str] = mapped_column(Text, default="unknown")
    is_gateway: Mapped[int] = mapped_column(Integer, default=0)
    open_ports: Mapped[str] = mapped_column(Text, default="[]")  # JSON [80,443,...]
    source: Mapped[str] = mapped_column(Text, default="[]")  # JSON ["tcp","arp",...]
    extra: Mapped[str] = mapped_column(Text, default="{}")  # JSON（UPnP 型号等）
    online: Mapped[int] = mapped_column(Integer, default=1)
    missed_scans: Mapped[int] = mapped_column(Integer, default=0)  # ≥3 判离线
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LanScanRun(Base):
    __tablename__ = "lan_scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(Text, default="devices")  # devices / db
    cidrs: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(Text, default="running")  # running/done/failed
    progress: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    found: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    gone_count: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class LanDeviceEvent(Base):
    __tablename__ = "lan_device_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[int | None] = mapped_column(Integer, default=None)
    ip: Mapped[str] = mapped_column(Text)
    mac: Mapped[str | None] = mapped_column(Text, default=None)
    event: Mapped[str] = mapped_column(Text)  # online / offline
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_lan_dev_events_ts", "device_id", "created_at"),)


class LanDbService(Base):
    __tablename__ = "lan_db_services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    host: Mapped[str] = mapped_column(Text)
    port: Mapped[int] = mapped_column(Integer)
    service_type: Mapped[str] = mapped_column(Text, default="unknown")
    version: Mapped[str | None] = mapped_column(Text, default=None)
    fingerprint: Mapped[str] = mapped_column(Text, default="{}")  # JSON 原始指纹
    credential_id: Mapped[int | None] = mapped_column(Integer, default=None)
    state: Mapped[str] = mapped_column(Text, default="unknown")  # up/down/unknown
    latency_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    online: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("uq_lan_db_host_port", "host", "port", unique=True),
    )


class DbCredential(Base, TimestampMixin):
    __tablename__ = "db_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, default="")
    service_type: Mapped[str] = mapped_column(Text)  # mysql/redis/minio
    host: Mapped[str] = mapped_column(Text)
    port: Mapped[int] = mapped_column(Integer)
    username: Mapped[str] = mapped_column(Text, default="")
    secret: Mapped[str] = mapped_column(Text, default="")  # Fernet 密文
    extra: Mapped[str] = mapped_column(Text, default="{}")  # JSON：database/use_ssl/db/region
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    last_test_ok: Mapped[int | None] = mapped_column(Integer, default=None)
