"""路由器 SNMP 增强（M19-6/7；dev-plan P26.4；api-spec §4.14）。

复用 services/snmp.py 纯标准库 BER 实现（GET/GETNEXT）：
- ifTable 双采样差分 → 各网口上下行速率与累计流量；
- ipNetToMediaTable 遍历 → 路由器侧在线设备（比本机 ARP 视角更全）。

SNMP 未配置/不可达时全部静默降级（返回空结果），不阻塞路由器详情页。
"""

from __future__ import annotations

import asyncio

from app.services import snmp as snmp_lib

IF_NUMBER = "1.3.6.1.2.1.2.1.0"
IF_ENTRY = "1.3.6.1.2.1.2.2.1"  # ifTable：2=descr 5=speed 10=in 16=out
IP_NET_TO_MEDIA = "1.3.6.1.2.1.4.22.1"  # 2=physAddress（OID 尾段即 IP）
WALK_LIMIT = 128  # 单列遍历上限（防异常设备拖死请求）


class _SnmpProtocol(asyncio.DatagramProtocol):
    def __init__(self, request: bytes, timeout: float) -> None:
        self.request = request
        self.timeout = timeout
        self.future: asyncio.Future = asyncio.get_running_loop().create_future()

    def connection_made(self, transport) -> None:  # noqa: ANN001
        transport.sendto(self.request)

    def datagram_received(self, data: bytes, addr) -> None:  # noqa: ANN001
        if not self.future.done():
            self.future.set_result(data)

    def error_received(self, exc: Exception) -> None:  # noqa: BLE001
        if not self.future.done():
            self.future.set_exception(exc)


async def snmp_request(host: str, request: bytes, timeout: float = 2.0) -> bytes:
    """单次 SNMP UDP 请求 → 响应字节；超时/不可达抛 OSError。"""
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: _SnmpProtocol(request, timeout), remote_addr=(host, 161)
    )
    try:
        return await asyncio.wait_for(protocol.future, timeout)
    finally:
        transport.close()


async def snmp_get(host: str, community: str, oid: str, timeout: float = 2.0):
    try:
        payload = await snmp_request(host, snmp_lib.build_get(oid, community), timeout)
        err, got_oid, (vtag, vbody) = snmp_lib.parse_response_tlv(payload)
        if err:
            return None
        return snmp_lib._decode_value((vtag, vbody))
    except (OSError, TimeoutError, ValueError):
        return None


async def snmp_walk(
    host: str, community: str, prefix: str, timeout: float = 2.0
) -> list[tuple[str, tuple[int, bytes]]]:
    """GETNEXT 遍历 prefix 子树：[(oid, (tag, raw_value))]；越界/超限即止。"""
    out: list[tuple[str, tuple[int, bytes]]] = []
    oid = prefix
    for _ in range(WALK_LIMIT):
        try:
            payload = await snmp_request(host, snmp_lib.build_getnext(oid, community), timeout)
            err, next_oid, tlv = snmp_lib.parse_response_tlv(payload)
        except (OSError, TimeoutError, ValueError):
            break
        if err or not next_oid.startswith(prefix + ".") :
            break
        out.append((next_oid, tlv))
        oid = next_oid
    return out


async def interfaces_once(host: str, community: str, timeout: float = 2.0) -> dict[str, dict]:
    """ifTable 单次采样：{index: {name, speed, in_octets, out_octets}}。"""
    rows: dict[str, dict] = {}
    for suffix, field in (("2", "name"), ("5", "speed"), ("10", "in_octets"), ("16", "out_octets")):
        for oid, (vtag, vbody) in await snmp_walk(host, community, f"{IF_ENTRY}.{suffix}", timeout):
            idx = oid.rsplit(".", 1)[1]
            value = snmp_lib._decode_value((vtag, vbody))
            if value is None:
                continue
            rows.setdefault(idx, {})[field] = value
    return rows


def _diff_rates(before: dict, after: dict, seconds: float) -> list[dict]:
    """双采样差分 → 每接口速率（bps）+ 累计字节数（计数器回绕按 2^32 容忍）。"""
    out: list[dict] = []
    for idx, a in after.items():
        b = before.get(idx)
        if not b:
            continue
        def _delta(key: str) -> int:
            d = (a.get(key) or 0) - (b.get(key) or 0)
            if d < 0:  # 32 位计数器回绕
                d += 1 << 32
            return d
        out.append({
            "index": idx,
            "name": str(a.get("name") or f"if{idx}")[:64],
            "speed_mbps": int(a.get("speed") or 0) // 1_000_000,
            "in_octets": int(a.get("in_octets") or 0),
            "out_octets": int(a.get("out_octets") or 0),
            "in_bps": int(_delta("in_octets") * 8 / seconds) if seconds > 0 else 0,
            "out_bps": int(_delta("out_octets") * 8 / seconds) if seconds > 0 else 0,
        })
    return sorted(out, key=lambda r: max(r["in_bps"], r["out_bps"]), reverse=True)


async def interface_rates(
    host: str, community: str, interval: float = 2.5, timeout: float = 2.0
) -> list[dict]:
    """双采样计算接口上下行速率（api-spec /api/lan/router/interfaces）。"""
    before = await interfaces_once(host, community, timeout)
    if not before:
        return []
    await asyncio.sleep(interval)
    after = await interfaces_once(host, community, timeout)
    return _diff_rates(before, after, interval)


async def router_arp(host: str, community: str, timeout: float = 2.0) -> list[dict]:
    """路由器侧 ipNetToMediaTable：[{ip, mac}]——OID 尾段即 IP，值为 MAC 原始字节。

    OID 形如 1.3.6.1.2.1.4.22.1.2.<ifIndex>.<ip 四段>，去掉前缀与 ifIndex 后
    恰好剩 4 段 IP，用 rsplit(., 5) 切出。
    """
    out: list[dict] = []
    for oid, (vtag, vbody) in await snmp_walk(host, community, f"{IP_NET_TO_MEDIA}.2", timeout):
        if vtag != 0x04 or len(vbody) != 6:
            continue
        parts = oid.rsplit(".", 5)
        if len(parts) != 6:
            continue
        try:
            ip = ".".join(str(int(p)) for p in parts[2:])
        except ValueError:
            continue
        out.append({"ip": ip, "mac": snmp_lib.hex_mac(vbody)})
    return out
