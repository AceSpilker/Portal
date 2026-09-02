"""网络环境服务（M04-8；dev-plan P3.1/P3.2）：CIDR 编译、档案匹配、来源 IP 解析。"""

from __future__ import annotations

from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.network import NetworkProfile


def compile_cidrs(cidrs: list[str]) -> list[IPv4Network | IPv6Network]:
    """把 CIDR 字符串列表编译为网络对象；非法输入抛 ValueError（由调用方转业务错误）。"""
    return [ip_network(c.strip(), strict=False) for c in cidrs]


def ip_matches(ip: str, cidrs: list[str]) -> bool:
    """判断 IP 是否落在任一网段内（边界地址含网络/广播地址；v4/v6 混排安全）。"""
    try:
        addr = ip_address(ip.strip())
        nets = compile_cidrs(cidrs)
    except ValueError:
        return False
    return any(addr.version == net.version and addr in net for net in nets)


def match_profile(ip: str, profiles: list[NetworkProfile]) -> NetworkProfile | None:
    """按 sort, id 顺序匹配启用的 cidr 档案；全部未命中返回默认兜底档案（可能为 None）。"""
    default: NetworkProfile | None = None
    for p in sorted(profiles, key=lambda x: (x.sort, x.id)):
        if not p.enabled:
            continue
        if p.match_type == "default":
            if default is None:
                default = p
            continue
        if ip_matches(ip, p.cidrs or []):
            return p
    return default


def client_ip_from_request(request: Request) -> str:
    """取请求来源 IP：NAS 反代场景优先 X-Forwarded-For 首段 / X-Real-IP，否则直连地址。"""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    real = request.headers.get("x-real-ip", "").strip()
    if real:
        return real
    return request.client.host if request.client else ""


async def enabled_profiles(session: AsyncSession) -> list[NetworkProfile]:
    """启用档案列表，按 sort, id 稳定排序（匹配顺序即此顺序）。"""
    rows = await session.execute(
        select(NetworkProfile)
        .where(NetworkProfile.enabled.is_(True))
        .order_by(NetworkProfile.sort, NetworkProfile.id)
    )
    return list(rows.scalars().all())


def order_urls_by_prefer(urls: list, prefer_types: list[str]) -> list:
    """按档案的入口类型优先顺序稳定排序；不在偏好中的类型排在末尾（保持原相对次序）。"""
    if not prefer_types:
        return list(urls)

    def _key(u):
        try:
            return (prefer_types.index(u.access_type), u.sort, u.id)
        except ValueError:
            return (len(prefer_types), u.sort, u.id)

    return sorted(urls, key=_key)
