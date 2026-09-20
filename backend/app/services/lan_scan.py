"""局域网设备扫描引擎（M19-1~3；dev-plan P26.1/P26.2；api-spec §4.14）。

设计要点（详见 docs/design-proposal §3.10）：
- 存活判定 = 并发 TCP connect 命中任意探测端口，或 ARP 邻居表存在记录；
  **不使用 ICMP**（容器无 CAP_NET_RAW 也可运行），零新增依赖；
- 扫描目标仅限私网 CIDR 白名单（10/8、172.16/12、192.168/16、169.254/16
  + `lan.extra_cidrs`），公网目标一律拒绝（防 SSRF 跳板）；
- 并发由 Semaphore（`lan.concurrency`）限速；同一时刻仅允许一个扫描任务。
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import psutil
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.lan import LanDevice, LanDeviceEvent, LanScanRun
from app.models.setting import Setting

PROBE_TIMEOUT = 1.5  # 单端口连接超时（秒）
GONE_THRESHOLD = 3  # 连续未命中次数 ≥ 此值判离线

# 第一梯队端口：任何命中即判存活（覆盖绝大多数设备），未命中再看第二梯队
_STAGE1_PORTS = (80, 445, 22, 443)

# 内置私网白名单（api-spec §4.14：扫描与数据库连接共用）
_PRIVATE_CIDRS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16")
PRIVATE_NETS = [ipaddress.ip_network(n) for n in _PRIVATE_CIDRS]


def is_private_ip(ip: str, extra_cidrs: list[str] | None = None) -> bool:
    """目标是否在允许的私网白名单内（含回环，允许查看 NAS 自身服务）。

    extra_cidrs 是管理员显式放行的扩展网段（如 CGNAT 100.64/10），优先于
    is_private 短路判断——否则扩展白名单永远不生效。
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.is_loopback:
        return True
    for cidr in extra_cidrs or []:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    if not addr.is_private:
        return False
    return any(addr in net for net in PRIVATE_NETS)


def validate_scan_cidrs(cidrs: list[str], extra_cidrs: list[str] | None = None) -> list[str]:
    """校验用户提交的扫描网段：非法/超私网范围的条目直接抛 ValueError。"""
    out: list[str] = []
    for raw in cidrs:
        try:
            net = ipaddress.ip_network(raw.strip(), strict=False)
        except ValueError as exc:
            raise ValueError(f"invalid cidr: {raw}") from exc
        if not is_private_ip(str(net.network_address), extra_cidrs):
            raise ValueError(f"cidr not allowed: {raw}")
        if net.num_addresses > 4096:  # /20 以上拒绝，防止误输大网段拖垮任务
            raise ValueError(f"cidr too large: {raw}")
        out.append(str(net))
    if not out:
        raise ValueError("no cidrs")
    return out


# ---- 配置读取 ----

LAN_KEYS = (
    "lan.scan_cidrs", "lan.auto_scan", "lan.scan_interval_min", "lan.probe_ports",
    "lan.dns_lookup", "lan.concurrency", "lan.extra_cidrs",
    "lan.snmp.enabled", "lan.snmp.community", "lan.snmp.timeout_s",
)


async def get_lan_config(session: AsyncSession) -> dict:
    """读 `lan.*` 设置键 → 归一化配置（snmp 为嵌套 dict，community 已解密）。"""
    raw: dict = {}
    for key in LAN_KEYS:
        row = await session.get(Setting, key)
        raw[key.removeprefix("lan.").replace(".", "_")] = json.loads(row.value) if row else None
    from app.core.secret_box import decrypt_secret

    cfg = {
        "scan_cidrs": [str(c) for c in (raw.get("scan_cidrs") or []) if isinstance(c, str)][:8],
        "auto_scan": bool(raw.get("auto_scan")),
        "scan_interval_min": max(0, int(raw.get("scan_interval_min") or 30)),
        "dns_lookup": bool(raw.get("dns_lookup")),
        "concurrency": max(16, min(512, int(raw.get("concurrency") or 128))),
        "extra_cidrs": [str(c) for c in (raw.get("extra_cidrs") or []) if isinstance(c, str)][:8],
        "snmp": {
            "enabled": bool(raw.get("snmp_enabled")),
            "community": decrypt_secret(str(raw.get("snmp_community") or "")),
            "timeout_s": max(0.5, min(10.0, float(raw.get("snmp_timeout_s") or 2.0))),
        },
    }
    ports = raw.get("probe_ports") or []
    cfg["probe_ports"] = [int(p) for p in ports if isinstance(p, int) and 1 <= p <= 65535][:32]
    if not cfg["probe_ports"]:
        cfg["probe_ports"] = list(_STAGE1_PORTS)
    return cfg


# ---- 网段识别（M19-1）：默认网关 + 网卡地址 → 所在网段 ----

def _proc_path(*parts: str) -> Path:
    host_proc = (settings.host_proc or "").strip() if hasattr(settings, "host_proc") else ""
    base = Path(host_proc) if host_proc else Path("/proc")
    return base.joinpath(*parts)


def default_gateway() -> tuple[str | None, str | None]:
    """读取系统默认网关：返回 (gateway_ip, iface)；读不到返回 (None, None)。"""
    import platform

    system = platform.system()
    try:
        if system == "Linux":
            text = _proc_path("net", "route").read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines()[1:]:
                cols = line.split()
                if len(cols) >= 8 and cols[1] == "00000000":
                    hex_ip = cols[2]
                    ip = ".".join(str(int(hex_ip[i:i + 2], 16)) for i in (6, 4, 2, 0))
                    return ip, cols[0]
        elif system == "Darwin":
            out = subprocess.run(  # noqa: S603 固定参数
                ["route", "-n", "get", "default"], capture_output=True, text=True, timeout=3,
            ).stdout
            gw = re.search(r"gateway:\s*(\S+)", out)
            iface = re.search(r"interface:\s*(\S+)", out)
            return (gw.group(1) if gw else None, iface.group(1) if iface else None)
        else:  # Windows
            out = subprocess.run(  # noqa: S603 固定参数
                ["route", "print", "-4", "0.0.0.0"], capture_output=True, text=True, timeout=5,
            ).stdout
            for line in out.splitlines():
                cols = line.split()
                gw_ok = re.match(r"\d+\.\d+\.\d+\.\d+", cols[3])
                if len(cols) >= 5 and cols[0] == "0.0.0.0" and gw_ok:
                    return cols[3], None
    except Exception:
        pass
    return None, None


def detect_segments() -> list[dict]:
    """自动识别本机所在网段：网卡 IPv4/掩码 → CIDR，标注默认网关所在网卡。"""
    gw_ip, gw_iface = default_gateway()
    segments: list[dict] = []
    addrs = psutil.net_if_addrs()
    for iface, if_addrs in addrs.items():
        for a in if_addrs:
            if a.family != socket.AF_INET:
                continue
            try:
                net = ipaddress.ip_network(f"{a.address}/{a.netmask}", strict=False)
            except ValueError:
                continue
            if net.prefixlen >= 31:  # 点对点/回环无扫描意义
                continue
            segments.append({
                "iface": iface,
                "address": a.address,
                "cidr": str(net),
                "is_gateway_iface": iface == (gw_iface or ""),
                "gateway": gw_ip if (gw_ip and ipaddress.ip_address(gw_ip) in net) else None,
            })
    # 默认网关所在网段排最前
    segments.sort(key=lambda s: not s["is_gateway_iface"])
    return segments


def cidr_from_ip(ip: str) -> str | None:
    """局域网 IP → 所属 /24（仅私网非回环地址有效；否则 None）。"""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if addr.is_loopback or addr.version != 4 or not is_private_ip(ip):
        return None
    return str(ipaddress.ip_network(f"{ip}/24", strict=False))


def auto_cidrs(hint_ips: list[str] | None = None) -> list[str]:
    """扫描网段缺省值，按优先级：

    1) Portal 访问地址提示（Host 头 IP / 客户端来源 IP）——容器部署时
       /proc/net 按网络命名空间生成（HOST_PROC 也拿不到宿主网络表），容器内
       自动识别只能看到 Docker 网桥；而管理员访问 Portal 用的就是 NAS 的
       局域网地址，是"NAS 所在网段"最可靠的信号源；
    2) 默认网关 /24（容器场景即 Docker 网桥，兜底可用）；
    3) 本机网卡网段。
    """
    for ip in hint_ips or []:
        cidr = cidr_from_ip(ip)
        if cidr:
            return [cidr]
    gw_ip, _ = default_gateway()
    if gw_ip:
        try:
            return [str(ipaddress.ip_network(f"{gw_ip}/24", strict=False))]
        except ValueError:
            pass
    seen: list[str] = []
    for seg in detect_segments():
        if seg["cidr"] not in seen:
            seen.append(seg["cidr"])
    return seen[:4]


# ---- ARP 邻居表 ----

_MAC_RE = re.compile(r"([0-9a-fA-F]{2}(?::|-)[0-9a-fA-F]{2}(?::|-)[0-9a-fA-F]{2}(?::|-)"
                     r"[0-9a-fA-F]{2}(?::|-)[0-9a-fA-F]{2}(?::|-)[0-9a-fA-F]{2})")
_IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


def _norm_mac(raw: str) -> str:
    return raw.strip().lower().replace("-", ":")


def read_arp_table() -> dict[str, str]:
    """读本机 ARP 邻居表：{ip: mac 规范小写冒号格式}。平台分支，失败返回空。"""
    import platform

    table: dict[str, str] = {}
    try:
        system = platform.system()
        if system == "Linux":
            path = _proc_path("net", "arp")
            text = path.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines()[1:]:
                cols = line.split()
                if len(cols) >= 4 and cols[2] != "0x0":
                    table[cols[0]] = _norm_mac(cols[3])
        else:
            import platform as _pf

            # macOS 用 -an（-a 会做反向 DNS，慢到超时）；Windows arp 无 -n
            cmd = ["arp", "-an"] if _pf.system() == "Darwin" else ["arp", "-a"]
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout  # noqa: S603
            for line in out.splitlines():
                ip_m = _IP_RE.search(line)
                mac_m = _MAC_RE.search(line)
                if ip_m and mac_m and mac_m.group(1).lower() != "ff:ff:ff:ff:ff:ff":
                    table[ip_m.group(1)] = _norm_mac(mac_m.group(1))
    except Exception:
        pass
    return table


# ---- MAC OUI 厂商（离线精简库：覆盖家庭 NAS 场景常见厂商，未命中返回 None） ----

OUI_VENDORS: dict[str, str] = {
    # 虚拟化
    "00:50:56": "VMware", "00:0C:29": "VMware", "00:1C:14": "VMware", "00:05:5A": "VMware",
    "08:00:27": "VirtualBox", "52:54:00": "QEMU/KVM",
    # NAS
    "00:11:32": "Synology", "90:09:D0": "Synology", "00:08:9B": "QNAP", "00:D0:B8": "QNAP",
    "24:5E:BE": "QNAP",
    # 单板机/开发板
    "B8:27:EB": "Raspberry Pi", "DC:A6:32": "Raspberry Pi", "E4:5F:01": "Raspberry Pi",
    "24:5A:4C": "Raspberry Pi", "D8:3A:DD": "Raspberry Pi", "A4:2B:B0": "Raspberry Pi",
    "28:CD:C1": "Raspberry Pi", "2C:CF:67": "Raspberry Pi",
    # 路由器/交换（家用为主）
    "CC:B8:A8": "TP-Link", "50:C7:BF": "TP-Link", "A4:2B:8C": "TP-Link", "14:CC:20": "TP-Link",
    "D8:07:B6": "TP-Link", "64:66:B3": "TP-Link", "F4:F2:6D": "TP-Link", "78:8A:20": "TP-Link",
    "C8:3A:35": "Tenda", "50:2B:73": "Tenda", "D4:6E:0E": "Tenda", "20:DC:E6": "Tenda",
    "54:E6:FC": "ASUS", "04:D4:C4": "ASUS", "10:7B:44": "ASUS",
    "AC:9E:17": "ASUS", "08:62:66": "ASUS",
    "00:1D:D8": "D-Link", "00:05:5D": "D-Link", "14:D6:4D": "D-Link", "B0:C5:54": "D-Link",
    "34:08:04": "D-Link", "C8:D3:A3": "D-Link",
    "00:14:6C": "Netgear", "A0:40:A0": "Netgear", "9C:3D:CF": "Netgear", "00:26:F2": "Netgear",
    "44:94:FC": "Netgear", "C0:3F:0E": "Netgear", "A0:63:91": "Netgear",
    "00:04:AC": "Ubiquiti", "24:A4:3C": "Ubiquiti", "F0:9F:C2": "Ubiquiti", "68:D7:9A": "Ubiquiti",
    "E0:63:DA": "Ubiquiti", "FC:EC:DA": "Ubiquiti",
    "48:8F:5A": "MikroTik", "D4:CA:6D": "MikroTik", "64:D1:54": "MikroTik", "E4:8D:8C": "MikroTik",
    "2C:C8:1B": "MikroTik",
    "00:0A:EB": "Ruijie", "C8:64:C7": "ZTE",
    # 手机/平板
    "AC:DE:48": "Apple", "00:1B:63": "Apple", "14:99:E2": "Apple", "F0:18:98": "Apple",
    "A4:83:E7": "Apple", "3C:15:C2": "Apple", "28:6A:BA": "Apple", "88:66:A5": "Apple",
    "34:80:B3": "Xiaomi", "64:09:80": "Xiaomi", "28:6C:07": "Xiaomi", "50:8F:4C": "Xiaomi",
    "8C:BE:BE": "Xiaomi", "04:CF:8C": "Xiaomi", "74:23:44": "Xiaomi", "5C:4C:A9": "Xiaomi",
    "18:59:36": "Xiaomi", "DC:ED:83": "Xiaomi",
    "DC:2C:6E": "Honor", "3C:BD:D8": "Honor", "88:28:B3": "Huawei", "34:6B:D3": "Huawei",
    "18:DE:D7": "Huawei", "78:1D:BA": "Huawei",
    "A4:77:33": "OPPO", "64:BC:0C": "OnePlus", "54:E1:AD": "vivo",
    # IoT/智能音箱/摄像头
    "10:CE:02": "Tuya", "68:57:2D": "Tuya", "7C:F6:66": "Broadlink", "24:DF:A7": "Broadlink",
    "38:A4:ED": "Espressif", "24:0A:C4": "Espressif", "30:AE:A4": "Espressif",
    "84:CC:A8": "Espressif", "5C:CF:7F": "Espressif", "BC:DD:C2": "Espressif",
    "74:C2:46": "Amazon", "6C:56:97": "Amazon", "D0:73:D5": "Google", "F4:F5:D8": "Google",
    "54:60:09": "Google", "00:17:88": "Philips Hue", "A0:02:DC": "Roku",
    "44:19:B6": "Hikvision", "4C:BD:8F": "Hikvision", "3C:EF:8C": "Dahua", "A0:BD:1D": "Dahua",
    # 打印机
    "00:1F:29": "HP", "3C:D9:2B": "HP", "00:17:A4": "HP", "C4:34:6B": "HP", "00:1E:0B": "HP",
    "00:1B:A9": "Brother", "00:80:92": "Brother", "30:05:5C": "Brother",
    "00:00:48": "Epson", "00:1B:25": "Epson", "00:1E:8F": "Canon", "00:17:C4": "Canon",
    "00:21:70": "Canon", "68:A8:6D": "Canon", "00:21:B5": "Lexmark",
    # PC/网卡
    "3C:A9:F4": "Intel", "A0:36:9F": "Intel", "00:27:10": "Intel", "8C:EC:4B": "Intel",
    "F8:34:41": "Intel", "00:24:D6": "Intel", "60:57:18": "Intel", "00:E0:4C": "Realtek",
    "54:EE:75": "Lenovo", "8C:16:45": "Lenovo", "14:F6:5A": "Lenovo",
    "F8:BC:12": "Dell", "00:14:22": "Dell", "18:03:73": "Dell", "F8:DB:88": "Dell",
    "00:16:32": "Samsung", "84:25:DB": "Samsung", "00:07:AB": "Samsung",
    "00:04:4B": "NVIDIA",
}


def lookup_vendor(mac: str | None) -> str | None:
    if not mac:
        return None
    parts = mac.upper().replace("-", ":").split(":")
    if len(parts) < 3:
        return None
    return OUI_VENDORS.get(":".join(parts[:3]))


# ---- 设备指纹（纯函数，便于单测） ----

_DB_PORTS = {3306, 6379, 5432, 27017, 9200, 11211, 2379, 8123, 9000}
_PRINTER_PORTS = {9100, 631, 515}
_PRINTER_VENDORS = {"HP", "Brother", "Seiko Epson", "Canon", "Lexmark"}
_IOT_VENDORS = {
    "Tuya", "Espressif", "Broadlink", "Philips Hue", "Amazon", "Xiaomi", "Hikvision", "Dahua",
}


def fingerprint_device(open_ports: list[int], vendor: str | None, is_gateway: bool) -> str:
    """端口特征 + OUI 厂商 → 设备类型标签（api-spec device_type 枚举）。"""
    if is_gateway:
        return "router"
    ports = set(open_ports)
    if ports & _PRINTER_PORTS or (vendor in _PRINTER_VENDORS and len(ports) <= 4):
        return "printer"
    if ports & _DB_PORTS:
        return "db"
    if vendor in {"Synology", "QNAP"} and not ports & {22, 3389, 5900, 445}:
        return "nas"  # NAS 厂商 OUI 且无通用管理端口特征
    if vendor in _IOT_VENDORS and not ports & {22, 3389}:
        return "iot"
    nas_vendor = vendor in {"Synology", "QNAP"}
    web_nas = 8080 in ports and 443 in ports and nas_vendor
    if 5000 in ports or 5001 in ports or 5050 in ports or web_nas:
        return "nas"
    if ports & {22, 3389, 5900, 445} or len(ports) >= 3:
        return "host"
    return "unknown"


# ---- 反向 DNS ----

async def resolve_hostnames(ips: list[str], enabled: bool = True) -> dict[str, str]:
    """并发反向 DNS（线程池 + 单个 800ms 超时上限），失败不写 hostname。"""
    if not enabled or not ips:
        return {}

    def _one(ip: str) -> tuple[str, str | None]:
        try:
            return ip, socket.gethostbyaddr(ip)[0]
        except Exception:
            return ip, None

    loop = asyncio.get_running_loop()
    results = await asyncio.gather(*(
        asyncio.wait_for(loop.run_in_executor(None, _one, ip), timeout=0.8)
        for ip in ips
    ))
    return {ip: name for ip, name in results if name}


# ---- TCP 扫描 ----

async def _tcp_open(host: str, port: int, timeout: float = PROBE_TIMEOUT) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except (OSError, TimeoutError):
        pass
    return True


async def scan_hosts(
    hosts: list[str], probe_ports: list[int], concurrency: int = 128,
) -> dict[str, list[int]]:
    """两阶段扫描：stage1 常见端口判存活（全部并发）；存活者再扫剩余端口补全清单。"""
    sem = asyncio.Semaphore(concurrency)
    stage1 = [p for p in _STAGE1_PORTS if p in probe_ports] or list(_STAGE1_PORTS)
    stage2 = [p for p in probe_ports if p not in stage1]

    async def _bounded(host: str, port: int) -> bool:
        async with sem:
            return await _tcp_open(host, port)

    async def _scan_host(host: str) -> tuple[str, list[int]]:
        hits = await asyncio.gather(*(_bounded(host, p) for p in stage1))
        open_ports = [p for p, hit in zip(stage1, hits) if hit]
        if not open_ports:
            return host, []
        if stage2:
            hits2 = await asyncio.gather(*(_bounded(host, p) for p in stage2))
            open_ports += [p for p, hit in zip(stage2, hits2) if hit]
        return host, sorted(set(open_ports))

    rows = await asyncio.gather(*(_scan_host(h) for h in hosts))
    return {h: ports for h, ports in rows if ports}


def _hosts_of(cidr: str) -> list[str]:
    net = ipaddress.ip_network(cidr, strict=False)
    it = net.hosts() if net.num_addresses > 2 else iter([str(net.network_address)])
    return [str(ip) for ip in it]


# ---- 设备合并与事件 ----

async def merge_scan_results(
    session: AsyncSession,
    found: dict[str, list[int]],
    arp: dict[str, str],
    hostnames: dict[str, str],
    gateway_ip: str | None,
    gateway_hint: str | None = None,
) -> dict:
    """扫描结果合并进 lan_devices；返回 {new, gone, events}（上下线翻转走通知）。

    gateway_hint：容器部署时默认网关是 Docker 网桥，不在被扫网段内——用
    提示网段的 .1（家用惯例）作为候选，仅在扫描确实发现该地址时标记。
    """
    gateway_candidates = {ip for ip in (gateway_ip, gateway_hint) if ip}
    now = datetime.utcnow()
    ips_seen = set(found) | {ip for ip in arp if is_private_ip(ip)}
    existing = {
        d.ip: d for d in (await session.execute(select(LanDevice))).scalars().all()
    }
    events: list[dict] = []
    new_count = 0

    def _is_gw(ip: str) -> bool:
        return ip in gateway_candidates

    for ip in ips_seen:
        mac = _norm_mac(arp[ip]) if arp.get(ip) else None
        vendor = lookup_vendor(mac)
        ports = found.get(ip, [])
        was = existing.get(ip)
        if was is None:
            dev = LanDevice(
                ip=ip, mac=mac, hostname=hostnames.get(ip), vendor=vendor,
                device_type=fingerprint_device(ports, vendor, _is_gw(ip)),
                is_gateway=1 if _is_gw(ip) else 0,
                open_ports=json.dumps(ports), source=json.dumps(
                    (["tcp"] if ports else []) + (["arp"] if mac else [])
                ),
                online=1, missed_scans=0, first_seen_at=now, last_seen_at=now,
            )
            session.add(dev)
            existing[ip] = dev
            new_count += 1
            events.append({"ip": ip, "mac": mac, "event": "online", "device_id": None})
        else:
            was_offline = not was.online
            was.last_seen_at = now
            was.missed_scans = 0
            was.online = 1
            if mac:
                was.mac = mac
                if vendor:
                    was.vendor = vendor
            if hostnames.get(ip):
                was.hostname = hostnames[ip]
            if ports:
                was.open_ports = json.dumps(ports)
            was.is_gateway = 1 if _is_gw(ip) else (0 if gateway_candidates else was.is_gateway)
            src = set(json.loads(was.source or "[]"))
            if ports:
                src.add("tcp")
            if mac:
                src.add("arp")
            was.source = json.dumps(sorted(src))
            if was_offline:
                events.append({
                    "ip": ip, "mac": mac or was.mac, "event": "online", "device_id": was.id,
                })

    gone_count = 0
    for ip, dev in existing.items():
        if ip in ips_seen:
            continue
        if dev.missed_scans + 1 >= GONE_THRESHOLD:
            if dev.online:
                dev.online = 0
                gone_count += 1
                events.append({"ip": ip, "mac": dev.mac, "event": "offline", "device_id": dev.id})
        else:
            dev.missed_scans += 1
    await session.commit()

    for ev in events:  # 事件落库（device_id 可空，保留 ip/mac 快照）
        session.add(LanDeviceEvent(**ev))
    if events:
        await session.commit()
    return {"new": new_count, "gone": gone_count, "events": events}


async def dispatch_device_events(events: list[dict]) -> None:
    """设备上下线事件 → 站内通知路由（source=lan）+ WS 广播。"""
    if not events:
        return
    from app.services import wsbus
    from app.services.notify import dispatch

    async with SessionLocal() as session:
        for ev in events:
            label = ev.get("ip") or ""
            if ev.get("mac"):
                label = f"{label} ({ev['mac']})"
            await dispatch(
                session,
                event="lan_device_online" if ev["event"] == "online" else "lan_device_offline",
                source="lan",
                title=f"设备上线 {label}" if ev["event"] == "online" else f"设备下线 {label}",
                body="",
                level="info" if ev["event"] == "online" else "warn",
            )
            await wsbus.broadcast({"type": "lan_device", "data": {
                "ip": ev.get("ip"), "mac": ev.get("mac"), "event": ev["event"],
            }})


# ---- 扫描任务（互斥；后台 asyncio task） ----

_current: dict | None = None  # {"run_id": int, "kind": str}；进行中任务标记


def scan_status() -> dict | None:
    return dict(_current) if _current else None


async def _run_scan(
    run_id: int, cidrs: list[str], cfg: dict, hint_ips: list[str] | None = None,
) -> None:
    """后台扫描主体：独立会话；异常写 failed 不抛出。"""
    global _current
    from app.services import lan_upnp

    arp = read_arp_table()
    gw_ip, _ = default_gateway()
    # 容器部署时默认网关是 Docker 网桥（不在被扫网段内），"路由器=网关"判定
    # 失效——退而用提示网段 +.1（家用网络惯例）作为候选，扫到才标记。
    nets = [ipaddress.ip_network(c) for c in cidrs]
    gw_hint: str | None = None
    if gw_ip and any(ipaddress.ip_address(gw_ip) in n for n in nets):
        pass  # 真实网关在被扫网段内，直接用
    else:
        for ip in hint_ips or []:
            c = cidr_from_ip(ip)
            if c and ipaddress.ip_network(c) in nets:
                gw_hint = str(ipaddress.ip_network(c).network_address + 1)
                break
        if gw_hint is None and nets:
            first = nets[0]
            candidate = str(first.network_address + 1)
            if ipaddress.ip_address(candidate) in first:
                gw_hint = candidate
    hosts: list[str] = []
    seen_hosts: set[str] = set()
    for cidr in cidrs:
        for h in _hosts_of(cidr):
            if h not in seen_hosts:
                seen_hosts.add(h)
                hosts.append(h)
    total = max(len(hosts), 1)
    found: dict[str, list[int]] = {}
    scanned = 0
    pending_events: list[dict] = []
    batch = max(8, cfg["concurrency"] // 8)
    async with SessionLocal() as session:
        try:
            for i in range(0, len(hosts), batch):
                chunk = hosts[i:i + batch]
                part = await scan_hosts(chunk, cfg["probe_ports"], cfg["concurrency"])
                found.update(part)
                scanned += len(chunk)
                run = await session.get(LanScanRun, run_id)
                run.progress = min(99, int(scanned * 100 / total))
                run.found = len(found)
                await session.commit()
            # ARP 表内的网段成员（未被 TCP 命中的休眠设备）也并入清单
            for cidr in cidrs:
                net = ipaddress.ip_network(cidr)
                for ip in arp:
                    try:
                        if ipaddress.ip_address(ip) in net:
                            found.setdefault(ip, [])
                    except ValueError:
                        continue
            hostnames = await resolve_hostnames(list(found), bool(cfg.get("dns_lookup")))
            merged = await merge_scan_results(
                session, found, arp, hostnames,
                gw_ip, gateway_hint=gw_hint,
            )
            pending_events = merged["events"]
            run = await session.get(LanScanRun, run_id)
            run.status = "done"
            run.progress = 100
            run.found = len(found)
            run.new_count = merged["new"]
            run.gone_count = merged["gone"]
            run.finished_at = datetime.utcnow()
            await session.commit()
        except Exception as exc:  # noqa: BLE001 后台任务不能裸抛
            run = await session.get(LanScanRun, run_id)
            if run:
                run.status = "failed"
                run.message = str(exc)[:300]
                run.finished_at = datetime.utcnow()
                await session.commit()
        finally:
            _current = None
    await dispatch_device_events(pending_events)
    # 路由器 UPnP 增强：对网关设备补型号/固件指纹（尽力而为，失败静默）
    if gw_ip:
        try:
            async with SessionLocal() as session:
                await lan_upnp.enrich_gateway(session, gw_ip)
        except Exception:
            pass


async def start_scan(
    session: AsyncSession, cidrs: list[str] | None = None, kind: str = "devices",
    hint_ips: list[str] | None = None,
) -> LanScanRun:
    """创建并启动扫描任务；已有任务进行中抛 LookupError（API 层转 4005）。

    网段缺省优先级：显式 cidrs → `lan.scan_cidrs` 设置 → Portal 访问地址
    派生网段（hint_ips）→ 容器网关 /24。
    """
    global _current
    if _current is not None:
        raise LookupError("scan busy")
    cfg = await get_lan_config(session)
    target = cidrs if cidrs else (cfg["scan_cidrs"] or auto_cidrs(hint_ips))
    target = validate_scan_cidrs(target, cfg["extra_cidrs"])
    total = len({h for c in target for h in _hosts_of(c)})
    run = LanScanRun(kind=kind, cidrs=json.dumps(target), status="running", total=total)
    session.add(run)
    await session.commit()
    _current = {"run_id": run.id, "kind": kind}
    asyncio.get_running_loop().create_task(_run_scan(run.id, target, cfg, hint_ips))
    return run


async def run_due_scans(session: AsyncSession) -> bool:
    """定时扫描（P26.5）：auto_scan 开启且距上次完成 ≥ scan_interval_min。"""
    global _current
    if _current is not None:
        return False
    cfg = await get_lan_config(session)
    if not cfg["auto_scan"] or cfg["scan_interval_min"] <= 0:
        return False
    last = (
        await session.execute(
            select(LanScanRun)
            .where(LanScanRun.kind == "devices", LanScanRun.status == "done")
            .order_by(LanScanRun.finished_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    now = datetime.utcnow()
    cooled = timedelta(minutes=cfg["scan_interval_min"])
    if last and last.finished_at and now - last.finished_at < cooled:
        return False
    try:
        await start_scan(session, kind="devices")
        return True
    except (LookupError, ValueError):
        return False
