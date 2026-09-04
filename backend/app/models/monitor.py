"""监控采样与阈值告警规则模型（M17-7/14/15；api-spec §3.4）。

monitor_samples 每分钟一行实时快照；io/temps 为 M2 列（P5 已用 temps，procs 预留）。
alert_rules 为 P10.3 阈值告警规则（metric/target/op/threshold/duration_min/level）。
ts 存 naive UTC（与全库约定一致）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

ALERT_METRICS = ("cpu", "mem", "disk", "disk_io", "temp")
ALERT_LEVELS = ("warn", "error")


class MonitorSample(Base):
    __tablename__ = "monitor_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # P21.3 多机纳管：采样来源节点（空=本机）
    node: Mapped[str] = mapped_column(Text, default="", server_default="")
    cpu: Mapped[float] = mapped_column(Float)  # 总使用率 %
    # JSON [每核使用率 %]（P5.5 历史每核曲线）
    cpu_cores: Mapped[str | None] = mapped_column(Text, default=None)
    load: Mapped[str | None] = mapped_column(Text, default=None)  # JSON [l1, l5, l15]
    mem: Mapped[str | None] = mapped_column(Text, default=None)  # JSON {total,used,swap_used,…}
    # JSON [{mount,total,used,inode_p}]
    disks: Mapped[str | None] = mapped_column(Text, default=None)
    nets: Mapped[str | None] = mapped_column(Text, default=None)  # JSON [{iface,rx_rate,tx_rate,…}]
    io: Mapped[str | None] = mapped_column(Text, default=None)  # JSON {read_rate,write_rate,iops,…}
    # JSON [{name,util,mem_used,mem_total}]
    gpu: Mapped[str | None] = mapped_column(Text, default=None)
    temps: Mapped[str | None] = mapped_column(Text, default=None)  # JSON [{name,current,…}]
    procs: Mapped[str | None] = mapped_column(Text, default=None)  # M2

    __table_args__ = (Index("ix_monitor_samples_ts", "ts"),)


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, default="")
    metric: Mapped[str] = mapped_column(Text, default="cpu")  # cpu/mem/disk/disk_io/temp
    target: Mapped[str | None] = mapped_column(Text, default=None)  # 如挂载点 "/"、传感器名
    op: Mapped[str] = mapped_column(Text, default=">")  # > / <
    threshold: Mapped[float] = mapped_column(Float, default=80.0)
    duration_min: Mapped[int] = mapped_column(Integer, default=5)
    level: Mapped[str] = mapped_column(Text, default="warn")  # warn / error
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
