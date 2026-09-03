"""服务器性能监控采集与历史聚合（M17-1~8；dev-plan P5.1~P5.4）。

采集：psutil 指向宿主机数据源——容器部署时 HOST_PROC/HOST_SYS 指向宿主只读
挂载（settings.host_proc/host_sys），未配置时读容器自身；Windows/Linux 均可用。
速率类指标（网卡上下行）由相邻两次计数快照差值计算；「当日流量」用跨日基线
（每日首个快照作为当日基准）。
"""

from __future__ import annotations

import json
import os
import platform
import time
from datetime import datetime, timedelta

import psutil
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.monitor import MonitorSample

RETENTION_KEY = "monitor.retention_days"
RETENTION_DEFAULT = 7

HISTORY_METRICS = ("cpu", "mem", "disk", "net")
RANGE_SECONDS = {"24h": 24 * 3600, "7d": 7 * 24 * 3600, "30d": 30 * 24 * 3600}
# 7d/30d 先按桶平均降点（约每 20min/1h 一点），24h 用原始分钟粒度
RANGE_BUCKET_SECONDS = {"24h": None, "7d": 20 * 60, "30d": 3600}


def setup_host_sources() -> None:
    """把 psutil 指向宿主机只读挂载（P5.1；api-spec §6.1 HOST_PROC/HOST_SYS）。"""
    if settings.host_proc:
        psutil.PROCFS_PATH = settings.host_proc


def prime_cpu_counters() -> None:
    """cpu_percent(interval=None) 首次调用返回 0，启动时先预热。"""
    psutil.cpu_percent(interval=None)
    psutil.cpu_percent(interval=None, percpu=True)


def collect_system() -> dict:
    """系统信息（M17-1）：主机名/系统/内核/架构/运行时长秒。"""
    return {
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "kernel": platform.version(),
        "arch": platform.machine(),
        "uptime": int(time.time() - psutil.boot_time()),
    }


def _load_avg() -> list[float | None]:
    try:
        l1, l5, l15 = psutil.getloadavg()
        return [round(l1, 2), round(l5, 2), round(l15, 2)]
    except Exception:  # 平台不支持时置空
        return [None, None, None]


def collect_cpu() -> dict:
    """CPU（M17-2）：总使用率 + 每核 + 负载均值（非阻塞快照）。"""
    return {
        "percent": psutil.cpu_percent(interval=None),
        "per_core": psutil.cpu_percent(interval=None, percpu=True),
        "load": _load_avg(),
        "cores": psutil.cpu_count(logical=True) or 0,
    }


def collect_mem() -> dict:
    """内存（M17-3）：已用/可用/缓存缓冲/Swap，字节为单位。"""
    vm = psutil.virtual_memory()
    sm = psutil.swap_memory()
    return {
        "total": vm.total,
        "used": vm.used,
        "available": vm.available,
        "percent": vm.percent,
        "buffers": getattr(vm, "buffers", 0) or 0,
        "cached": getattr(vm, "cached", 0) or 0,
        "swap_total": sm.total,
        "swap_used": sm.used,
        "swap_percent": sm.percent,
    }


def _inode_percent(mount: str) -> float | None:
    try:
        st = os.statvfs(mount)  # Linux/Unix 专属，Windows 恒为 None
    except (AttributeError, OSError):
        return None
    if st.f_files == 0:
        return None
    return round((st.f_files - st.f_favail) / st.f_files * 100, 1)


def collect_disks() -> list[dict]:
    """磁盘分区（M17-4）：容量/已用/使用率/inode 用量。"""
    out: list[dict] = []
    for p in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(p.mountpoint)
        except OSError:
            continue
        out.append(
            {
                "mount": p.mountpoint,
                "total": u.total,
                "used": u.used,
                "percent": u.percent,
                "inode_p": _inode_percent(p.mountpoint),
            }
        )
    return out


def net_snapshot() -> dict[str, tuple[int, int]]:
    """网卡计数快照 {iface: (rx_total, tx_total)}，剔除回环口。"""
    counters = psutil.net_io_counters(pernic=True)
    return {
        name: (c.bytes_recv, c.bytes_sent)
        for name, c in counters.items()
        if not name.lower().startswith("lo")
    }


class NetRateCalculator:
    """由相邻快照差值计算速率并维护「当日流量」基线（M17-5）。

    feed 返回每个网卡的 {iface, rx_rate, tx_rate, rx_total, tx_total,
    rx_today, tx_today}；计数器回绕/重启导致的负增量按 0 处理。
    间隔不足 MIN_ELAPSED 的快照（如 HTTP 与 WS 两路推送交替触发）
    不重算速率，沿用上一窗口值，避免除以极小间隔产生尖峰。
    """

    MIN_ELAPSED = 1.0

    def __init__(self) -> None:
        self._last: dict[str, tuple[int, int]] | None = None
        self._last_ts = 0.0
        self._day = ""
        self._day_base: dict[str, tuple[int, int]] = {}
        self._last_rates: dict[str, tuple[float, float]] = {}

    def feed(self, snap: dict[str, tuple[int, int]], ts: float | None = None) -> list[dict]:
        ts = time.time() if ts is None else ts
        day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        if day != self._day:  # 跨日：以昨日最后快照为今日基线
            self._day = day
            self._day_base = dict(self._last) if self._last else dict(snap)
        elapsed = ts - self._last_ts if self._last and ts > self._last_ts else 0.0
        reliable = elapsed >= self.MIN_ELAPSED
        out: list[dict] = []
        for name, (rx, tx) in sorted(snap.items()):
            if reliable and self._last and name in self._last:
                prx, ptx = self._last[name]
                rx_rate = round(max(0.0, (rx - prx) / elapsed), 1)
                tx_rate = round(max(0.0, (tx - ptx) / elapsed), 1)
                self._last_rates[name] = (rx_rate, tx_rate)
            else:
                rx_rate, tx_rate = self._last_rates.get(name, (0.0, 0.0))
            # 中途新出现的网卡：首见即登记基线，当日流量从 0 起算
            base_rx, base_tx = self._day_base.setdefault(name, (rx, tx))
            out.append(
                {
                    "iface": name,
                    "rx_rate": rx_rate,
                    "tx_rate": tx_rate,
                    "rx_total": rx,
                    "tx_total": tx,
                    "rx_today": max(0, rx - base_rx),
                    "tx_today": max(0, tx - base_tx),
                }
            )
        self._last = dict(snap)
        self._last_ts = ts
        return out


# 实时推送（2s 粒度）与分钟采样各持一份计算器，互不干扰
ws_net_calc = NetRateCalculator()
sample_net_calc = NetRateCalculator()


def collect_overview(net_calc: NetRateCalculator) -> dict:
    """实时概览（M17-1~5；WS /ws/monitor 与 GET /monitor/system 共用）。"""
    return {
        "ts": datetime.utcnow().isoformat() + "Z",
        "system": collect_system(),
        "cpu": collect_cpu(),
        "mem": collect_mem(),
        "disks": collect_disks(),
        "nets": net_calc.feed(net_snapshot()),
    }


# ---- 采样入库与清理（P5.2）----


async def sample_once(session: AsyncSession) -> MonitorSample:
    """写入一行分钟级采样（json 列按 api-spec §3.4 结构）。"""
    row = MonitorSample(
        cpu=psutil.cpu_percent(interval=None),
        cpu_cores=json.dumps(psutil.cpu_percent(interval=None, percpu=True)),
        load=json.dumps(_load_avg()),
        mem=json.dumps(collect_mem()),
        disks=json.dumps(collect_disks()),
        nets=json.dumps(sample_net_calc.feed(net_snapshot())),
    )
    session.add(row)
    await session.commit()
    return row


async def read_retention_days(session: AsyncSession) -> int:
    from app.models.setting import Setting

    row = await session.get(Setting, RETENTION_KEY)
    if row is None:
        return RETENTION_DEFAULT
    try:
        days = int(json.loads(row.value))
    except (ValueError, TypeError):
        return RETENTION_DEFAULT
    return days if days > 0 else RETENTION_DEFAULT


async def cleanup_expired(session: AsyncSession, retention_days: int | None = None) -> int:
    """删除超过保留天数的采样行，返回删除行数（M17-7）。"""
    if retention_days is None:
        retention_days = await read_retention_days(session)
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    res = await session.execute(delete(MonitorSample).where(MonitorSample.ts < cutoff))
    await session.commit()
    return res.rowcount or 0


# ---- 历史查询与聚合（P5.4）----


def _bucket_avg(rows: list[MonitorSample], bucket: int | None, value_of):
    """按桶平均取点；24h（bucket=None）原样输出。value_of(row) 返回该行的点值字典列表。"""
    points: list[dict] = []
    if bucket is None:
        for r in rows:
            points.append({"ts": r.ts.isoformat() + "Z", **value_of(r)})
        return points
    acc: dict[int, list] = {}
    since = rows[0].ts if rows else None
    for r in rows:
        key = int((r.ts - since).total_seconds()) // bucket
        acc.setdefault(key, []).append(r)
    for key in sorted(acc):
        group = acc[key]
        merged: dict[str, list] = {}
        for r in group:
            for k, v in value_of(r).items():
                merged.setdefault(k, []).append(v)
        points.append(
            {
                "ts": group[-1].ts.isoformat() + "Z",
                **{k: _merge_avg(v) for k, v in merged.items()},
            }
        )
    return points


def _merge_avg(values: list):
    """桶内均值：标量取平均；列表（每核序列）按位平均（核数恒定，短序列补齐末值）。"""
    first = values[0]
    if not isinstance(first, (list, tuple)):
        return round(sum(values) / len(values), 2)
    n = max(len(v) for v in values)
    cols = zip(*(v + [v[-1]] * (n - len(v)) for v in values))
    return [round(sum(col) / len(col), 2) for col in cols]


def _avg(vals: list) -> float:
    return round(sum(vals) / len(vals), 2)


async def build_history(session: AsyncSession, metric: str, rng: str) -> dict:
    """历史曲线（M17-6）。cpu/mem/net → points[]；disk → mounts[{mount, points[]}]。"""
    if metric not in HISTORY_METRICS:
        raise ValueError(f"unsupported metric: {metric}")
    if rng not in RANGE_SECONDS:
        raise ValueError(f"unsupported range: {rng}")
    since = datetime.utcnow() - timedelta(seconds=RANGE_SECONDS[rng])
    rows = list(
        (
            await session.execute(
                select(MonitorSample).where(MonitorSample.ts >= since).order_by(MonitorSample.ts)
            )
        ).scalars()
    )
    bucket = RANGE_BUCKET_SECONDS[rng]

    def _nets_sum(r: MonitorSample) -> dict:
        nets = json.loads(r.nets) if r.nets else []
        return {
            "rx": round(sum(n.get("rx_rate", 0) for n in nets), 1),
            "tx": round(sum(n.get("tx_rate", 0) for n in nets), 1),
        }

    if metric == "cpu":
        def _cpu(r: MonitorSample) -> dict:
            cores = json.loads(r.cpu_cores) if r.cpu_cores else None
            return {"cpu": r.cpu, **({"cores": cores} if cores else {})}

        return {
            "metric": metric,
            "range": rng,
            "points": _bucket_avg(rows, bucket, _cpu),
        }
    if metric == "mem":
        def _mem(r: MonitorSample) -> dict:
            m = json.loads(r.mem) if r.mem else {}
            total = m.get("total") or 0
            used = m.get("used") or 0
            return {"used": used, "percent": round(used / total * 100, 2) if total else 0}

        return {"metric": metric, "range": rng, "points": _bucket_avg(rows, bucket, _mem)}
    if metric == "net":
        return {"metric": metric, "range": rng, "points": _bucket_avg(rows, bucket, _nets_sum)}

    # disk：全挂载点共享统一时间轴（缺失时刻补 null，保证前端多序列 x 轴对齐）
    acc: dict[str, dict[datetime, list]] = {}
    for r in rows:
        for d in json.loads(r.disks) if r.disks else []:
            acc.setdefault(d["mount"], {}).setdefault(r.ts, []).append(d.get("percent", 0))

    if bucket is None:  # 24h：时间轴 = 全部行时间戳去重升序
        timeline = sorted({r.ts for r in rows})
        out = [
            {
                "mount": m,
                "points": [
                    {"ts": ts.isoformat() + "Z", "percent": _avg(vals[ts]) if ts in vals else None}
                    for ts in timeline
                ],
            }
            for m, vals in sorted(acc.items())
        ]
        return {"metric": "disk", "range": rng, "mounts": out}

    # 桶模式：全局 origin 划桶，桶 ts 统一取桶尾，各挂载点输出等长序列
    origin = rows[0].ts
    n_buckets = int((rows[-1].ts - origin).total_seconds()) // bucket + 1
    out = []
    for m, by_ts in sorted(acc.items()):
        by_key: dict[int, list] = {}
        for ts, vals in by_ts.items():
            by_key.setdefault(int((ts - origin).total_seconds()) // bucket, []).extend(vals)
        out.append(
            {
                "mount": m,
                "points": [
                    {
                        "ts": (origin + timedelta(seconds=(k + 1) * bucket)).isoformat() + "Z",
                        "percent": _avg(by_key[k]) if k in by_key else None,
                    }
                    for k in range(n_buckets)
                ],
            }
        )
    return {"metric": "disk", "range": rng, "mounts": out}
