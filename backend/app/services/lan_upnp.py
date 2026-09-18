"""UPnP IGD 路由器发现（M19-4/5；dev-plan P26.3；api-spec §4.14 /api/lan/router）。

纯标准库实现：SSDP M-SEARCH（UDP 组播 239.255.255.250:1900）→ rootDesc.xml
（XML 解析型号/厂商/固件）→ SOAP 控制调用（GetExternalIPAddress /
GetStatusInfo 取外网 IP 与连接状态）。全程零新增依赖；IGD 关闭时静默降级。
"""

from __future__ import annotations

import asyncio
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

SSDP_ADDR = ("239.255.255.250", 1900)
SSDP_TIMEOUT = 2.5
HTTP_TIMEOUT = 3.0

_M_SEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    "HOST: 239.255.255.250:1900\r\n"
    "MAN: \"ssdp:discover\"\r\n"
    "MX: 2\r\n"
    "ST: {st}\r\n"
    "\r\n"
)
_IGD_STS = (
    "urn:schemas-upnp-org:device:InternetGatewayDevice:1",
    "urn:schemas-upnp-org:device:InternetGatewayDevice:2",
    "upnp:rootdevice",
)


class _SSDPProtocol(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.responses: list[str] = []
        self.done = asyncio.Event()

    def datagram_received(self, data: bytes, addr) -> None:  # noqa: ANN001
        self.responses.append(data.decode("utf-8", "replace"))

    def error_received(self, exc: Exception) -> None:  # noqa: BLE001
        pass


async def ssdp_discover(
    timeout: float = SSDP_TIMEOUT, sts: tuple[str, ...] = _IGD_STS
) -> list[dict]:
    """组播 M-SEARCH 收集设备应答：[{st, location, server, usn}]（按 location 去重）。"""
    loop = asyncio.get_running_loop()
    try:
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: _SSDPProtocol(), local_addr=("0.0.0.0", 0)
        )
    except OSError:
        return []
    try:
        for st in sts:
            transport.sendto(_M_SEARCH.format(st=st).encode(), SSDP_ADDR)
        try:
            await asyncio.wait_for(protocol.done.wait(), timeout)
        except TimeoutError:
            pass  # 收集窗口结束即返回已有应答
    finally:
        transport.close()

    found: dict[str, dict] = {}
    for raw in protocol.responses:
        location = re.search(r"(?i)^LOCATION:\s*(\S+)", raw, re.M)
        if not location:
            continue
        loc = location.group(1)
        entry = found.setdefault(loc, {"location": loc})
        for key in ("SERVER", "USN", "ST"):
            m = re.search(rf"(?i)^{key}:\s*(.+)$", raw, re.M)
            if m and key.lower() not in entry:
                entry[key.lower()] = m.group(1).strip()
    return list(found.values())


def parse_root_desc(xml_text: str) -> dict:
    """解析 rootDesc.xml：设备信息 + WANIPConnection/WANPPPConnection 控制点。

    兼容带 xmlns 与裸 XML 两类固件输出（按 local-name 匹配元素）。
    """
    root = ET.fromstring(xml_text)

    def _el(parent: ET.Element | None, name: str) -> ET.Element | None:
        if parent is None:
            return None
        for el in parent.iter():
            if el.tag.split("}")[-1] == name:
                return el
        return None

    def _text(parent: ET.Element | None, name: str) -> str:
        el = _el(parent, name)
        return (el.text or "").strip() if el is not None and el.text else ""

    device = _el(root, "device")
    info: dict = {
        "friendly_name": _text(device, "friendlyName"),
        "manufacturer": _text(device, "manufacturer"),
        "model_name": _text(device, "modelName"),
        "model_number": _text(device, "modelNumber"),
        "model_description": _text(device, "modelDescription"),
        "serial_number": _text(device, "serialNumber"),
        "services": [],
    }
    for svc in root.iter():
        if svc.tag.split("}")[-1] != "service":
            continue
        stype = _text(svc, "serviceType")
        if not re.search(r"WAN(IP|PPP)Connection", stype):
            continue
        info["services"].append({"service_type": stype, "control_url": _text(svc, "controlURL")})
    return info


async def soap_action(base_url: str, control_url: str, service_type: str, action: str,
                      args: dict[str, str] | None = None) -> str:
    """SOAP 控制调用，返回原始响应 XML（解析由调用方做，失败抛异常）。"""
    url = urljoin(base_url, control_url)
    arg_xml = "".join(f"<{k}>{v}</{k}>" for k, v in (args or {}).items())
    body = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f'<s:Body><m:{action} xmlns:m="{service_type}">'
        f"{arg_xml}</m:{action}></s:Body></s:Envelope>"
    )
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(url, content=body, headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPACTION": f'"{service_type}#{action}"',
        })
        resp.raise_for_status()
        return resp.text


def _soap_value(xml_text: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>([^<]*)</{tag}>", xml_text)
    return m.group(1).strip() if m else None


async def router_info(only_host: str | None = None) -> dict | None:
    """路由器识别主入口：SSDP → rootDesc → WAN 状态。识别不到返回 None。"""
    entries = await ssdp_discover()
    target = None
    for entry in entries:
        host = urlsplit(entry["location"]).hostname or ""
        if only_host and host != only_host:
            continue
        hay = entry.get("st", "") + entry.get("server", "")
        if re.search(r"(?i)InternetGatewayDevice|router|gateway", hay):
            target = entry
            break
    if target is None and entries and not only_host:
        target = entries[0]
    if target is None:
        return None
    base = target["location"]
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(base)
            resp.raise_for_status()
            desc = parse_root_desc(resp.text)
    except Exception:
        return None
    info: dict = {
        "location": base,
        "server": target.get("server", ""),
        **{k: v for k, v in desc.items() if k != "services"},
        "external_ip": None,
        "connection_status": None,
        "uptime_seconds": None,
    }
    for svc in desc["services"]:
        try:
            ip_xml = await soap_action(
                base, svc["control_url"], svc["service_type"], "GetExternalIPAddress"
            )
            info["external_ip"] = _soap_value(ip_xml, "NewExternalIPAddress") or info["external_ip"]
            status_xml = await soap_action(
                base, svc["control_url"], svc["service_type"], "GetStatusInfo"
            )
            info["connection_status"] = (
                _soap_value(status_xml, "NewConnectionStatus") or info["connection_status"]
            )
            uptime = _soap_value(status_xml, "NewUptime")
            if uptime and uptime.isdigit():
                info["uptime_seconds"] = int(uptime)
            break  # 第一个可用控制点成功即止
        except Exception:
            continue
    return info


async def enrich_gateway(session: AsyncSession, gw_ip: str) -> dict | None:
    """把 UPnP 识别结果写进网关设备的 extra/类型（扫描任务收尾时调用）。"""
    from sqlalchemy import select

    from app.models.lan import LanDevice

    info = await router_info(only_host=gw_ip)
    if info is None:
        return None
    dev = (
        await session.execute(select(LanDevice).where(LanDevice.ip == gw_ip))
    ).scalar_one_or_none()
    if dev is None:
        return info
    extra = json.loads(dev.extra or "{}")
    extra["upnp"] = {k: v for k, v in info.items() if k != "location"}
    dev.extra = json.dumps(extra, ensure_ascii=False)
    dev.device_type = "router"
    dev.is_gateway = 1
    src = set(json.loads(dev.source or "[]"))
    src.add("upnp")
    dev.source = json.dumps(sorted(src))
    await session.commit()
    return info
