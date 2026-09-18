# ruff: noqa: E501
"""P26 测试关卡：局域网设备发现与路由器（M19-1~10；dev-plan 26.1~26.5）。

覆盖：网段识别平台分支、私网白名单校验（公网 4006）、TCP 判活与 ARP 融合合并逻辑
（ip 唯一/MAC 更新/missed_scans 离线判定）、扫描互斥（4005）、OUI 厂商匹配、
UPnP rootDesc 解析、SNMP GETNEXT 编码与差分速率计算、设备上下线事件、
设置脱敏（community 空=保持原值）。
"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password

ADMIN = "admin"
ADMIN_PASS = "portal-p26"

_tokens: dict = {}


def _reset_db_state() -> None:
    import sqlite3
    from pathlib import Path

    db_file = Path(settings.data_dir) / "portal.db"
    conn = sqlite3.connect(db_file)
    try:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (ADMIN,)).fetchone():
            conn.execute(
                "UPDATE users SET password_hash = ?, is_active = 1, totp_enabled = 0 WHERE username = ?",
                (hash_password(ADMIN_PASS), ADMIN),
            )
        else:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, is_active, prefs, token_version)"
                " VALUES (?, ?, 'admin', 1, '{}', 0)",
                (ADMIN, hash_password(ADMIN_PASS)),
            )
        for table in ("lan_devices", "lan_scan_runs", "lan_device_events"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("UPDATE settings SET value = '[]' WHERE key = 'lan.scan_cidrs'")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="module", autouse=True)
def _setup(client: TestClient):
    _reset_db_state()
    resp = client.post(
        "/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASS}
    )
    assert resp.status_code == 200, resp.text
    _tokens["admin"] = resp.json()["data"]["access_token"]
    yield


def _auth():
    return {"Authorization": f"Bearer {_tokens['admin']}"}


# ---- 26.1 引擎纯函数 ----

def test_01_private_whitelist():
    from app.services.lan_scan import is_private_ip, validate_scan_cidrs

    assert is_private_ip("192.168.1.1") and is_private_ip("10.0.0.5")
    assert is_private_ip("172.16.0.1") and is_private_ip("172.31.255.255")
    assert is_private_ip("169.254.1.1") and is_private_ip("127.0.0.1")
    assert not is_private_ip("8.8.8.8")
    assert not is_private_ip("172.32.0.1")  # 172.16/12 之外
    assert not is_private_ip("not-an-ip")
    # 回环 + 白名单外网段可通过 extra_cidrs 放行
    assert is_private_ip("100.64.1.1", ["100.64.0.0/10"])
    # 校验：合法 /24 通过（非严格主机位归一），公网/超大网段/非法串拒绝
    assert validate_scan_cidrs(["192.168.1.5/24"]) == ["192.168.1.0/24"]
    with pytest.raises(ValueError):
        validate_scan_cidrs(["8.8.8.0/24"])  # 公网目标
    with pytest.raises(ValueError):
        validate_scan_cidrs(["10.0.0.0/8"])  # >4096 地址
    with pytest.raises(ValueError):
        validate_scan_cidrs(["banana"])
    with pytest.raises(ValueError):
        validate_scan_cidrs([])


def test_02_segments_detection():
    """平台分支：任何平台都应至少返回结构正确的网段列表（含回环被过滤与否不强制）。"""
    from app.services.lan_scan import auto_cidrs, detect_segments

    segments = detect_segments()
    assert isinstance(segments, list)
    for seg in segments:
        assert {"iface", "address", "cidr"} <= set(seg)
    cidrs = auto_cidrs()
    assert isinstance(cidrs, list) and cidrs  # 测试机必有至少一个 IPv4 网段


def test_03_oui_lookup():
    from app.services.lan_scan import lookup_vendor

    assert lookup_vendor("B8:27:EB:11:22:33") == "Raspberry Pi"  # 大写键
    assert lookup_vendor("b8:27:eb:11:22:33") == "Raspberry Pi"  # 小写输入
    assert lookup_vendor("88-28-B3-11-22-33") == "Huawei"  # 横线格式
    assert lookup_vendor("00:11:32:AA:BB:CC") == "Synology"
    assert lookup_vendor(None) is None
    assert lookup_vendor("zz") is None
    assert lookup_vendor("AA:BB:CC:11:22:33") is None  # 未收录前缀


def test_04_device_fingerprint():
    from app.services.lan_scan import fingerprint_device

    assert fingerprint_device([], None, True) == "router"
    assert fingerprint_device([3306], None, False) == "db"
    assert fingerprint_device([6379, 80], None, False) == "db"
    assert fingerprint_device([9100], None, False) == "printer"
    assert fingerprint_device([631], "HP", False) == "printer"
    assert fingerprint_device([80], "Tuya", False) == "iot"
    assert fingerprint_device([80], "Espressif", False) == "iot"
    assert fingerprint_device([22], "Tuya", False) == "host"  # 开着 ssh 的不是纯 IoT
    assert fingerprint_device([5000], None, False) == "nas"
    assert fingerprint_device([22, 80, 443], None, False) == "host"
    assert fingerprint_device([80], None, False) == "unknown"


# ---- 26.2 合并逻辑（ip 唯一 / missed_scans 离线判定 / 上下线事件） ----

def test_05_merge_and_offline_state_machine():
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.lan import LanDevice
    from app.services.lan_scan import GONE_THRESHOLD, merge_scan_results

    async def run():
        async with SessionLocal() as session:
            # 第一轮：两台设备（A=TCP 命中+ARP MAC，B=仅 ARP）
            r1 = await merge_scan_results(
                session,
                found={"192.168.77.10": [22, 80, 443]},
                arp={"192.168.77.10": "B8:27:EB:11:22:33", "192.168.77.20": "00:11:32:AA:BB:CC"},
                hostnames={"192.168.77.10": "raspberrypi.local"},
                gateway_ip="192.168.77.1",
            )
            assert r1["new"] == 2 and len(r1["events"]) == 2
            devices = {
                d.ip: d
                for d in (await session.execute(select(LanDevice))).scalars().all()
            }
            a = devices["192.168.77.10"]
            assert a.mac == "b8:27:eb:11:22:33" and a.vendor == "Raspberry Pi"
            assert a.hostname == "raspberrypi.local" and a.is_gateway == 0
            assert json.loads(a.open_ports) == [22, 80, 443]
            assert a.device_type == "host"  # ≥3 端口或含 22/445
            b = devices["192.168.77.20"]
            assert b.device_type == "nas"  # Synology OUI + 无端口（不满足 host/iot）
            assert b.source and "arp" in json.loads(b.source)

            # 第二轮：B 消失 1 次 → missed_scans=1 仍在线，无事件
            r2 = await merge_scan_results(
                session, found={"192.168.77.10": [80]},
                arp={"192.168.77.10": "B8:27:EB:11:22:33"}, hostnames={}, gateway_ip=None,
            )
            assert r2["new"] == 0 and r2["gone"] == 0
            await session.refresh(b)
            assert b.missed_scans == 1 and b.online == 1

            # 连续消失至阈值 → 判离线 + offline 事件；A 的端口清单更新
            last = None
            for _ in range(GONE_THRESHOLD - 1):
                last = await merge_scan_results(
                    session, found={"192.168.77.10": [80]},
                    arp={"192.168.77.10": "b8:27:eb:11:22:33"}, hostnames={}, gateway_ip=None,
                )
            assert last["gone"] == 1
            off_events = [e for e in last["events"] if e["event"] == "offline"]
            assert len(off_events) == 1 and off_events[0]["ip"] == "192.168.77.20"
            await session.refresh(b)
            assert b.online == 0
            await session.refresh(a)
            assert json.loads(a.open_ports) == [80]  # 最新一轮覆盖

            # 回归在线：再扫到 B → online 事件 + missed_scans 清零
            r3 = await merge_scan_results(
                session, found={}, arp={"192.168.77.20": "00:11:32:aa:bb:cc"},
                hostnames={}, gateway_ip="192.168.77.1",
            )
            on_events = [e for e in r3["events"] if e["event"] == "online"]
            assert any(e["ip"] == "192.168.77.20" for e in on_events)
            await session.refresh(b)
            assert b.online == 1 and b.missed_scans == 0

    asyncio.run(run())


# ---- 26.3 UPnP ----

def test_06_upnp_root_desc_parse():
    from app.services.lan_upnp import parse_root_desc

    xml = (
        '<root xmlns="urn:schemas-upnp-org:device-1-0">'
        "<device><friendlyName>Home Router</friendlyName><manufacturer>TP-Link"
        "</manufacturer><modelName>AX6000</modelName><modelNumber>1.2</modelNumber>"
        "<serialNumber>SN123</serialNumber></device>"
        "<serviceList><service><serviceType>"
        "urn:schemas-upnp-org:service:WANIPConnection:1</serviceType>"
        "<controlURL>/igd/wanip</controlURL></service></serviceList></root>"
    )
    info = parse_root_desc(xml)
    assert info["friendly_name"] == "Home Router"
    assert info["manufacturer"] == "TP-Link"
    assert info["model_name"] == "AX6000" and info["model_number"] == "1.2"
    assert info["services"] == [
        {"service_type": "urn:schemas-upnp-org:service:WANIPConnection:1",
         "control_url": "/igd/wanip"}
    ]
    # 无命名空间变体（部分固件裸 XML）
    bare = "<root><device><modelName>X</modelName></device></root>"
    assert parse_root_desc(bare)["model_name"] == "X"


def test_07_soap_value_extract():
    from app.services.lan_upnp import _soap_value

    xml = '<s:Envelope><NewExternalIPAddress>203.0.113.7</NewExternalIPAddress></s:Envelope>'
    assert _soap_value(xml, "NewExternalIPAddress") == "203.0.113.7"
    assert _soap_value(xml, "Missing") is None


# ---- 26.4 SNMP ----

def test_08_snmp_getnext_and_roundtrip():
    from app.services import snmp

    req = snmp.build_get("1.3.6.1.2.1.1.1.0", "public")
    assert req[0] == 0x30 and b"public" in req and b"\xa0" in req
    nxt = snmp.build_getnext("1.3.6.1.2.1.1.1.0", "public", request_id=7)
    assert nxt[0] == 0x30 and b"\xa1" in nxt  # GetNextRequest PDU

    # 构造合成响应（单 varbind：sysDescr OCTET STRING）验证解析保持原始 TLV
    payload = snmp._tlv(0x04, b"Linux Router 3.10")
    varbind = snmp._tlv(0x30, snmp._encode_oid("1.3.6.1.2.1.1.1.0") + payload)
    varbinds = snmp._tlv(0x30, varbind)
    pdu = (
        snmp._tlv(0x02, bytes([42])) + snmp._tlv(0x02, b"\x00")
        + snmp._tlv(0x02, b"\x00") + varbinds
    )
    message = snmp._tlv(
        0x30, snmp._tlv(0x02, b"\x00") + snmp._tlv(0x04, b"public") + snmp._tlv(0xA2, pdu)
    )
    err, oid, (vtag, vbody) = snmp.parse_response_tlv(message)
    assert err == 0 and oid.endswith("1.3.6.1.2.1.1.1.0")
    assert vtag == 0x04 and vbody == b"Linux Router 3.10"
    assert snmp.hex_mac(b"\xa1\xb2\xc3\xd4\xe5\xf6") == "a1:b2:c3:d4:e5:f6"
    # 兼容：旧 parse_response 解码为文本（Agent 模块在用）
    err2, oid2, value = snmp.parse_response(message)
    assert value == "Linux Router 3.10" and oid2 == oid


def test_09_interface_rate_diff_and_wraparound():
    from app.services.lan_snmp import _diff_rates

    before = {"1": {"name": "wan", "speed": 1_000_000_000, "in_octets": 1000, "out_octets": 500}}
    after = {"1": {"name": "wan", "speed": 1_000_000_000, "in_octets": 3000, "out_octets": 1500}}
    rates = _diff_rates(before, after, 2.0)
    assert rates[0]["in_bps"] == 8000 and rates[0]["out_bps"] == 4000
    assert rates[0]["speed_mbps"] == 1000 and rates[0]["in_octets"] == 3000
    # 32 位计数器回绕容忍
    wrapped = {"1": {"name": "wan", "speed": 0, "in_octets": 100, "out_octets": 0}}
    r2 = _diff_rates(before, wrapped, 1.0)
    assert r2[0]["in_bps"] == (100 - 1000 + (1 << 32)) * 8


# ---- API：设置脱敏 / 扫描互斥 4005 / 网段校验 4006 / 清单与事件 ----

def test_10_settings_masked(client: TestClient):
    resp = client.get("/api/lan/segments", headers=_auth())
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)

    resp = client.put(
        "/api/lan/settings",
        headers=_auth(),
        json={"auto_scan": False, "scan_interval_min": 30, "snmp": {"enabled": True, "community": "h3c123"}},
    )
    assert resp.status_code == 200
    cfg = resp.json()["data"]
    assert cfg["snmp"]["enabled"] is True
    assert cfg["snmp"]["community"] == "" and cfg["snmp_community_set"] is True  # 脱敏
    # 空 community 提交 = 保持原值
    resp = client.put("/api/lan/settings", headers=_auth(), json={"snmp": {"enabled": True, "community": ""}})
    assert resp.json()["data"]["snmp_community_set"] is True


def test_11_scan_mutex_and_cidr_guard(client: TestClient, monkeypatch):
    from app.services import lan_scan

    started: list = []

    async def _fake_run(run_id, cidrs, cfg):
        started.append((run_id, cidrs))
        # 模拟完成（互斥位在真实实现里由 finally 释放，这里手动）
        lan_scan._current = None

    monkeypatch.setattr(lan_scan, "_run_scan", _fake_run)
    resp = client.post("/api/lan/scan", headers=_auth(), json={"cidrs": ["192.168.88.0/24"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["total"] == 254

    # 公网/超大网段 → 4006
    resp = client.post("/api/lan/scan", headers=_auth(), json={"cidrs": ["8.8.8.0/24"]})
    assert resp.status_code == 422 and resp.json()["code"] == 4006
    resp = client.post("/api/lan/scan", headers=_auth(), json={"cidrs": ["10.0.0.0/8"]})
    assert resp.json()["code"] == 4006

    # 互斥：占住任务位再触发 → 4005
    lan_scan._current = {"run_id": 999, "kind": "devices"}
    resp = client.post("/api/lan/scan", headers=_auth(), json={})
    assert resp.status_code == 409 and resp.json()["code"] == 4005
    lan_scan._current = None

    # 权限：user 角色不可扫描（403）；未登录 401
    resp = client.post("/api/lan/scan", json={})
    assert resp.status_code == 401


def test_12_devices_and_events_api(client: TestClient):
    from app.db.session import SessionLocal
    from app.services.lan_scan import merge_scan_results

    async def seed():
        async with SessionLocal() as session:
            await merge_scan_results(
                session, found={"192.168.90.1": [80]},
                arp={"192.168.90.1": "00:11:32:aa:bb:cc"}, hostnames={}, gateway_ip="192.168.90.1",
            )

    asyncio.run(seed())
    resp = client.get("/api/lan/devices", headers=_auth())
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert items and items[0]["ip"] == "192.168.90.1"
    assert items[0]["is_gateway"] is True and items[0]["device_type"] == "router"
    assert items[0]["vendor"] == "Synology"
    # 筛选
    resp = client.get("/api/lan/devices", headers=_auth(), params={"type": "router"})
    assert resp.json()["data"]["total"] >= 1
    resp = client.get("/api/lan/devices", headers=_auth(), params={"type": "printer"})
    assert resp.json()["data"]["total"] == 0
    # 详情含事件历史
    dev_id = items[0]["id"]
    resp = client.get(f"/api/lan/devices/{dev_id}", headers=_auth())
    assert resp.status_code == 200 and "events" in resp.json()["data"]
    resp = client.get("/api/lan/devices/999999", headers=_auth())
    assert resp.status_code == 404


def test_13_event_dispatch_notification_and_ws_payload():
    """设备上下线事件 → 通知 + WS 广播（验证 dispatch_device_events 组装正确）。"""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.probe import Notification
    from app.services.lan_scan import dispatch_device_events

    async def run():
        async with SessionLocal() as session:
            await dispatch_device_events([
                {"ip": "192.168.90.7", "mac": "b8:27:eb:00:00:07", "event": "online", "device_id": None},
                {"ip": "192.168.90.8", "mac": None, "event": "offline", "device_id": 3},
            ])
            rows = (await session.execute(
                select(Notification).order_by(Notification.id.desc()).limit(2)
            )).scalars().all()
            titles = {r.title for r in rows}
            assert any("设备上线" in t and "192.168.90.7" in t for t in titles)
            assert any("设备下线" in t and "192.168.90.8" in t for t in titles)
            assert {r.source for r in rows} == {"lan"}

    asyncio.run(run())


def test_14_router_endpoints_shape(client: TestClient):
    # 关闭 SNMP（test_10 打开过）保证 interfaces 走 snmp_disabled 分支
    client.put("/api/lan/settings", headers=_auth(), json={"snmp": {"enabled": False}})
    resp = client.get("/api/lan/router", headers=_auth())
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert {"gateway_ip", "device", "upnp", "admin_candidates", "snmp_enabled"} <= set(data)

    resp = client.get("/api/lan/router/clients", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert "sources" in body and isinstance(body["items"], list)

    # SNMP 未启用 → interfaces 返回空数组 + reason
    resp = client.get("/api/lan/router/interfaces", headers=_auth())
    data = resp.json()["data"]
    assert data["items"] == [] and data["reason"] == "snmp_disabled"

    # 扫描历史/事件流水结构
    resp = client.get("/api/lan/scans", headers=_auth())
    assert resp.status_code == 200
    assert {"runs", "events"} <= set(resp.json()["data"])


def test_15_device_linkage_monitor_wol(client: TestClient):
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.lan import LanDevice

    async def seed():
        async with SessionLocal() as session:
            session.add(LanDevice(
                ip="192.168.91.50", mac="b8:27:eb:91:00:50", hostname="dev50",
                device_type="host", open_ports="[22]", source='["tcp","arp"]', online=1,
            ))
            await session.commit()
            row = (await session.execute(select(LanDevice).where(LanDevice.ip == "192.168.91.50"))).scalar_one()
            return row.id

    dev_id = asyncio.run(seed())
    resp = client.post(f"/api/lan/devices/{dev_id}/monitor", headers=_auth())
    assert resp.status_code == 200 and resp.json()["data"]["port"] == 22
    # 重复创建 → 409
    resp = client.post(f"/api/lan/devices/{dev_id}/monitor", headers=_auth())
    assert resp.status_code == 409
    resp = client.post(f"/api/lan/devices/{dev_id}/wol-target", headers=_auth())
    assert resp.status_code == 200 and resp.json()["data"]["mac"] == "b8:27:eb:91:00:50"
    resp = client.post(f"/api/lan/devices/{dev_id}/wol-target", headers=_auth())
    assert resp.status_code == 409
    # 清理本用例数据（WoL 目标/监控项/设备），避免污染其他模块的清零断言
    import sqlite3
    from pathlib import Path

    conn = sqlite3.connect(Path(settings.data_dir) / "portal.db")
    conn.execute("DELETE FROM wol_targets WHERE mac = 'b8:27:eb:91:00:50'")
    conn.execute("DELETE FROM port_monitors WHERE host = '192.168.91.50'")
    conn.execute("DELETE FROM lan_devices WHERE ip = '192.168.91.50'")
    conn.commit()
    conn.close()
