"""局域网设备与路由器接口（M19；dev-plan P26.2~P26.5；api-spec §4.14）。

- /api/lan/segments|settings|scan|scan/status|devices|scans：网段识别、扫描设置与任务、
  设备清单与事件流水；
- /api/lan/router(/clients|/interfaces|/snmp/test)：路由器聚合视图、连接设备双来源、
  SNMP 接口速率、community 即测即用；
- 设备联动：一键建端口监控项（M18）/ 加 WoL 目标（M10-1）。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_admin
from app.core.i18n import t
from app.core.response import (
    CODE_CIDR_FORBIDDEN,
    CODE_DUPLICATED,
    CODE_NOT_FOUND,
    CODE_SCAN_BUSY,
    CODE_VALIDATION,
    BizError,
    ok,
)
from app.core.secret_box import encrypt_secret
from app.db.session import get_session
from app.models.lan import LanDevice, LanDeviceEvent, LanScanRun
from app.models.port import PortMonitor
from app.models.setting import Setting
from app.models.tools import WolTarget
from app.models.user import User
from app.services import lan_scan, lan_snmp, lan_upnp
from app.services.audit import client_ip, write_audit

router = APIRouter()


async def lan_scan_due_job() -> None:
    """调度任务（P26.5，每 60s）：定时扫描到期判断（auto_scan 开启才生效）。"""
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        await lan_scan.run_due_scans(session)

ROUTER_ADMIN_PORTS = (80, 443, 8080, 8443, 8006, 5000)  # 管理后台常见端口（命中即给直达候选）


def _device_view(d: LanDevice) -> dict:
    return {
        "id": d.id, "ip": d.ip, "mac": d.mac, "hostname": d.hostname, "vendor": d.vendor,
        "device_type": d.device_type, "is_gateway": bool(d.is_gateway),
        "open_ports": json.loads(d.open_ports or "[]"),
        "source": json.loads(d.source or "[]"),
        "extra": json.loads(d.extra or "{}"),
        "online": bool(d.online), "first_seen_at": d.first_seen_at, "last_seen_at": d.last_seen_at,
    }


# ---- 网段识别与设置 ----

@router.get("/lan/segments")
async def get_segments(_: User = Depends(get_current_user)):
    """自动识别的本机网卡/默认网关/所在网段（设置页预填）。"""
    return ok(lan_scan.detect_segments())


@router.get("/lan/settings")
async def get_settings_(
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    cfg = await lan_scan.get_lan_config(session)
    cfg["snmp_community_set"] = bool(cfg["snmp"].pop("community"))
    cfg["snmp"]["community"] = ""
    return ok(cfg)


@router.put("/lan/settings")
async def put_settings_(
    body: dict, _: User = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    """保存扫描设置；SNMP community 空=保持原值（加密存储）。"""
    simple = {
        "scan_cidrs": [str(c)[:64] for c in (body.get("scan_cidrs") or [])][:8],
        "auto_scan": bool(body.get("auto_scan", False)),
        "scan_interval_min": max(0, min(1440, int(body.get("scan_interval_min") or 30))),
        "probe_ports": [
            int(p) for p in (body.get("probe_ports") or [])
            if isinstance(p, int) and 1 <= p <= 65535
        ][:32],
        "dns_lookup": bool(body.get("dns_lookup", True)),
        "concurrency": max(16, min(512, int(body.get("concurrency") or 128))),
        "extra_cidrs": [str(c)[:64] for c in (body.get("extra_cidrs") or [])][:8],
        "snmp.enabled": bool((body.get("snmp") or {}).get("enabled", False)),
        "snmp.timeout_s": max(
            0.5, min(10.0, float((body.get("snmp") or {}).get("timeout_s") or 2.0))
        ),
    }
    for suffix, value in simple.items():
        await session.merge(Setting(key=f"lan.{suffix}", value=json.dumps(value)))
    community = str((body.get("snmp") or {}).get("community") or "")
    if community:
        await session.merge(
            Setting(key="lan.snmp.community", value=json.dumps(encrypt_secret(community)))
        )
    await session.commit()
    cfg = await lan_scan.get_lan_config(session)
    cfg["snmp_community_set"] = bool(cfg["snmp"].pop("community"))
    cfg["snmp"]["community"] = ""
    return ok(cfg, t("ok.saved"))


# ---- 扫描任务 ----

@router.post("/lan/scan")
async def post_scan(
    request: Request, body: dict | None = None,
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    """触发网段扫描（后台任务）；已有任务 4005，网段不合法/超私网 4006。"""
    body = body or {}
    cidrs = [str(c)[:64] for c in (body.get("cidrs") or [])]
    try:
        run = await lan_scan.start_scan(session, cidrs or None)
    except LookupError as exc:
        raise BizError(CODE_SCAN_BUSY, t("err.lan_scan_busy"), 409) from exc
    except ValueError as exc:
        raise BizError(
            CODE_CIDR_FORBIDDEN, t("err.lan_cidr_invalid", cidr=str(exc)[:120]), 422
        ) from exc
    await write_audit(session, _.id, "lan_scan", f"cidrs={json.loads(run.cidrs)}",
                      client_ip(request))
    await session.commit()
    return ok({"run_id": run.id, "cidrs": json.loads(run.cidrs), "total": run.total})


@router.get("/lan/scan/status")
async def get_scan_status(
    _: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    """当前扫描进度 + 最近 5 次运行记录。"""
    run = None
    if lan_scan.scan_status():
        run = await session.get(LanScanRun, lan_scan.scan_status()["run_id"])
    recent = (
        await session.execute(select(LanScanRun).order_by(desc(LanScanRun.id)).limit(5))
    ).scalars().all()
    return ok({
        "current": _run_view(run) if run else None,
        "recent": [_run_view(r) for r in recent],
    })


def _run_view(r: LanScanRun) -> dict:
    return {
        "id": r.id, "kind": r.kind, "cidrs": json.loads(r.cidrs or "[]"), "status": r.status,
        "progress": r.progress, "total": r.total, "found": r.found,
        "new_count": r.new_count, "gone_count": r.gone_count, "message": r.message,
        "started_at": r.started_at, "finished_at": r.finished_at,
    }


# ---- 设备清单 ----

_TYPE_ORDER = {"router": 0, "nas": 1, "db": 2, "host": 3, "iot": 4, "printer": 5, "unknown": 9}


@router.get("/lan/devices")
async def list_devices(
    type: str = "", online: str = "",
    _: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
):
    """设备清单：路由器/网关置顶，其余按类型+IP 排序；?type=&online= 过滤。"""
    rows = (await session.execute(select(LanDevice))).scalars().all()
    items = [_device_view(d) for d in rows]
    if type:
        items = [i for i in items if i["device_type"] == type]
    if online in ("0", "1"):
        items = [i for i in items if i["online"] == (online == "1")]
    items.sort(key=lambda i: (
        not i["is_gateway"], _TYPE_ORDER.get(i["device_type"], 9),
        tuple(int(p) for p in i["ip"].split(".")),
    ))
    return ok({"items": items, "total": len(items)})


@router.get("/lan/devices/{device_id}")
async def get_device(
    device_id: int, _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    dev = await session.get(LanDevice, device_id)
    if dev is None:
        raise BizError(CODE_NOT_FOUND, t("err.lan_device_not_found"), 404)
    events = (
        await session.execute(
            select(LanDeviceEvent)
            .where(LanDeviceEvent.device_id == device_id)
            .order_by(desc(LanDeviceEvent.id)).limit(50)
        )
    ).scalars().all()
    view = _device_view(dev)
    view["events"] = [
        {"event": e.event, "created_at": e.created_at} for e in events
    ]
    return ok(view)


@router.get("/lan/scans")
async def list_scans(
    limit: int = 50, _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """扫描历史 + 设备上下线事件流水（api-spec §4.14）。"""
    runs = (
        await session.execute(select(LanScanRun).order_by(desc(LanScanRun.id)).limit(limit))
    ).scalars().all()
    events = (
        await session.execute(
            select(LanDeviceEvent).order_by(desc(LanDeviceEvent.id)).limit(limit)
        )
    ).scalars().all()
    return ok({
        "runs": [_run_view(r) for r in runs],
        "events": [
            {"id": e.id, "device_id": e.device_id, "ip": e.ip, "mac": e.mac,
             "event": e.event, "created_at": e.created_at}
            for e in events
        ],
    })


@router.post("/lan/devices/{device_id}/monitor")
async def create_monitor(
    device_id: int, request: Request, body: dict | None = None,
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    """设备一键建端口监控项（M18 联动）：默认取第一个开放端口。"""
    dev = await session.get(LanDevice, device_id)
    if dev is None:
        raise BizError(CODE_NOT_FOUND, t("err.lan_device_not_found"), 404)
    ports = json.loads(dev.open_ports or "[]")
    body = body or {}
    port = int(body.get("port") or (ports[0] if ports else 80))
    dup = (
        await session.execute(
            select(PortMonitor).where(PortMonitor.host == dev.ip, PortMonitor.port == port)
        )
    ).scalar_one_or_none()
    if dup:
        raise BizError(CODE_DUPLICATED, t("err.already_exists", name=f"{dev.ip}:{port}"), 409)
    m = PortMonitor(
        name=dev.hostname or dev.ip, host=dev.ip, port=port, interval=60, enabled=1,
    )
    session.add(m)
    await write_audit(session, _.id, "lan_monitor", f"{dev.ip}:{port}", client_ip(request))
    await session.commit()
    return ok({"id": m.id, "host": m.host, "port": m.port})


@router.post("/lan/devices/{device_id}/wol-target")
async def create_wol_target(
    device_id: int, request: Request,
    _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    """设备一键加入 WoL 唤醒目标（M10-1 联动，需 MAC）。"""
    dev = await session.get(LanDevice, device_id)
    if dev is None:
        raise BizError(CODE_NOT_FOUND, t("err.lan_device_not_found"), 404)
    if not dev.mac:
        raise BizError(CODE_VALIDATION, t("v.invalid", field="mac"), 422)
    dup = (
        await session.execute(select(WolTarget).where(WolTarget.mac == dev.mac))
    ).scalar_one_or_none()
    if dup:
        raise BizError(CODE_DUPLICATED, t("err.already_exists", name=dev.mac), 409)
    w = WolTarget(name=dev.hostname or dev.ip, mac=dev.mac, note=f"lan:{dev.ip}")
    session.add(w)
    await write_audit(session, _.id, "lan_wol", dev.mac, client_ip(request))
    await session.commit()
    return ok({"id": w.id, "mac": w.mac})


# ---- 路由器 ----

async def _gateway_device(session: AsyncSession) -> LanDevice | None:
    dev = (
        await session.execute(
            select(LanDevice).where(LanDevice.is_gateway == 1).limit(1)
        )
    ).scalar_one_or_none()
    if dev is not None:
        return dev
    gw_ip, _ = lan_scan.default_gateway()
    if not gw_ip:
        return None
    return (
        await session.execute(
            select(LanDevice).where(LanDevice.ip == gw_ip).limit(1)
        )
    ).scalar_one_or_none()


@router.get("/lan/router")
async def get_router(
    _: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
):
    """路由器聚合视图：设备信息 + UPnP 型号/固件 + WAN 状态 + 管理后台候选。"""
    cfg = await lan_scan.get_lan_config(session)
    dev = await _gateway_device(session)
    base: dict = {
        "gateway_ip": getattr(dev, "ip", None) or (lan_scan.default_gateway()[0]),
        "device": _device_view(dev) if dev else None,
        "upnp": None,
        "admin_candidates": [],
        "snmp_enabled": bool(cfg["snmp"].get("enabled")),
    }
    if dev:
        upnp_info = json.loads(dev.extra or "{}").get("upnp")
        if not upnp_info:  # 库里没有则即时尝试一次（缓存缺失时兜底）
            upnp_info = await lan_upnp.router_info(only_host=dev.ip)
        base["upnp"] = upnp_info
        base["admin_candidates"] = [
            f"http://{dev.ip}:{p}" if p not in (443, 8443) else f"https://{dev.ip}:{p}"
            for p in json.loads(dev.open_ports or "[]") if p in ROUTER_ADMIN_PORTS
        ]
    return ok(base)


@router.get("/lan/router/clients")
async def get_router_clients(
    _: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
):
    """连接设备表：本机 ARP + 路由器 SNMP ipNetToMedia 双来源（api-spec §4.14）。"""
    cfg = await lan_scan.get_lan_config(session)
    arp = lan_scan.read_arp_table()
    rows: dict[str, dict] = {}
    for ip, mac in arp.items():
        rows[ip] = {"ip": ip, "mac": mac, "source": "local-arp",
                    "vendor": lan_scan.lookup_vendor(mac)}
    sources = {"local-arp"}
    gw = await _gateway_device(session)
    if cfg["snmp"].get("enabled") and gw:
        remote = await lan_snmp.router_arp(
            gw.ip, cfg["snmp"].get("community") or "public",
            float(cfg["snmp"].get("timeout_s") or 2.0),
        )
        for item in remote:
            row = rows.get(item["ip"])
            if row:
                row["source"] = "snmp+local-arp"
            else:
                rows[item["ip"]] = {"ip": item["ip"], "mac": item["mac"],
                                    "source": "snmp", "vendor": lan_scan.lookup_vendor(item["mac"])}
            sources.add("snmp")
    items = sorted(rows.values(), key=lambda r: tuple(int(p) for p in r["ip"].split(".")))
    return ok({"items": items, "total": len(items), "sources": sorted(sources)})


@router.get("/lan/router/interfaces")
async def get_router_interfaces(
    _: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
):
    """SNMP ifTable 双采样接口速率；未配置/不可达返回空数组（前端隐藏卡片）。"""
    cfg = await lan_scan.get_lan_config(session)
    if not cfg["snmp"].get("enabled"):
        return ok({"items": [], "reason": "snmp_disabled"})
    gw = await _gateway_device(session)
    if gw is None:
        return ok({"items": [], "reason": "no_gateway"})
    items = await lan_snmp.interface_rates(
        gw.ip, cfg["snmp"].get("community") or "public",
        interval=2.5, timeout=float(cfg["snmp"].get("timeout_s") or 2.0),
    )
    return ok({"items": items, "reason": None if items else "snmp_unreachable"})


@router.post("/lan/router/snmp/test")
async def snmp_test(
    body: dict, _: User = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    """SNMP v2c community 即测即用（body 可带未保存的 community/host）。"""
    community = str(body.get("community") or "")
    if not community:
        cfg = await lan_scan.get_lan_config(session)
        community = cfg["snmp"].get("community") or ""
    host = str(body.get("host") or "")
    if not host:
        gw = await _gateway_device(session)
        host = gw.ip if gw else (lan_scan.default_gateway()[0] or "")
    if not host:
        raise BizError(CODE_VALIDATION, t("v.missing", field="host"), 422)
    value = await lan_snmp.snmp_get(host, community, "1.3.6.1.2.1.1.1.0", timeout=2.0)
    if value is None:
        return ok({"ok": False, "detail": "SNMP 无应答（检查 community/路由器 SNMP 开关）"})
    return ok({"ok": True, "detail": str(value)[:200]})
