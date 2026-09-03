"""监控采样模型（M17-7；api-spec §3.4 monitor_samples）。

每分钟一行实时快照；io/temps/procs 为 M2 预留列（本阶段恒为 NULL）。
ts 存 naive UTC（与全库约定一致）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MonitorSample(Base):
    __tablename__ = "monitor_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    cpu: Mapped[float] = mapped_column(Float)  # 总使用率 %
    # JSON [每核使用率 %]（P5.5 历史每核曲线）
    cpu_cores: Mapped[str | None] = mapped_column(Text, default=None)
    load: Mapped[str | None] = mapped_column(Text, default=None)  # JSON [l1, l5, l15]
    mem: Mapped[str | None] = mapped_column(Text, default=None)  # JSON {total,used,swap_used,…}
    # JSON [{mount,total,used,inode_p}]
    disks: Mapped[str | None] = mapped_column(Text, default=None)
    nets: Mapped[str | None] = mapped_column(Text, default=None)  # JSON [{iface,rx_rate,tx_rate,…}]
    io: Mapped[str | None] = mapped_column(Text, default=None)  # M2
    temps: Mapped[str | None] = mapped_column(Text, default=None)  # M2
    procs: Mapped[str | None] = mapped_column(Text, default=None)  # M2

    __table_args__ = (Index("ix_monitor_samples_ts", "ts"),)
