"""局域网数据库服务指纹扫描（M20-1/2；dev-plan P27.1；api-spec §4.15）。

常见数据库端口并发 TCP 探测 + 协议握手指纹（零凭据即可识别类型与版本）：
- MySQL 3306：连接即收 greeting 包，首段 NUL 结尾字符串 = 服务器版本；
- Redis 6379：PING / INFO server（未认证时 INFO 报错，仍可凭错误格式识别）；
- MinIO 9000/9001：GET /minio/health/live（200）+ Server 响应头；
- PostgreSQL 5432：SSLRequest（8 字节）→ 单字节 'N'/'S' 应答；
- MongoDB 27017：OP_MSG hello 应答 opcode 2013；
- Elasticsearch 9200：GET / → JSON version.number；
- Memcached 11211：version 命令；etcd 2379：GET /health；ClickHouse 8123：GET /ping。
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.models.lan import LanDbService, LanScanRun
from app.services.lan_scan import (
    _hosts_of,
    get_lan_config,
    scan_status,
    validate_scan_cidrs,
)

CONNECT_TIMEOUT = 2.0
HTTP_TIMEOUT = 3.0

# 端口 → 服务类型（同端口多义时按握手指纹裁决）
DB_PORTS: dict[int, str] = {
    3306: "mysql",
    6379: "redis",
    9000: "minio",
    9001: "minio",
    5432: "postgresql",
    27017: "mongodb",
    9200: "elasticsearch",
    11211: "memcached",
    2379: "etcd",
    8123: "clickhouse",
}


# ---- 协议指纹（每个函数：已连上的 reader/writer → 指纹 dict 或 None） ----

async def _read_exactly(reader: asyncio.StreamReader, n: int) -> bytes:
    return await asyncio.wait_for(reader.readexactly(n), CONNECT_TIMEOUT)


async def fingerprint_mysql(reader: asyncio.StreamReader) -> dict | None:
    """MySQL greeting：4 字节头 + payload[0]=协议版本(10) + NUL 结尾版本串。"""
    try:
        head = await _read_exactly(reader, 4)
        length = head[0] | (head[1] << 8) | (head[2] << 16)
        if not 20 <= length <= 4096 or head[3] != 0:
            return None
        payload = await _read_exactly(reader, length)
        if payload[0] != 10:
            return None
        version = payload[1:].split(b"\x00", 1)[0].decode("utf-8", "replace")
        return {"type": "mysql", "version": version, "detail": {"protocol": 10}}
    except (OSError, TimeoutError, asyncio.IncompleteReadError, IndexError):
        return None


async def fingerprint_redis(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> dict | None:
    """Redis：PING → +PONG；INFO server → bulk 文本（未认证报 -NOAUTH，也足以识别）。"""
    try:
        writer.write(b"PING\r\n")
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), CONNECT_TIMEOUT)
        if not line.startswith(b"+") and not line.startswith(b"-"):
            return None
        writer.write(b"INFO server\r\n")
        await writer.drain()
        info_line = await asyncio.wait_for(reader.readline(), CONNECT_TIMEOUT)
        detail: dict = {}
        version = None
        if info_line.startswith(b"$"):
            body = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), CONNECT_TIMEOUT)
            for row in body.decode("utf-8", "replace").splitlines():
                if row.startswith("redis_version:"):
                    version = row.split(":", 1)[1]
                if row.startswith(("redis_mode:", "os:")):
                    k, v = row.split(":", 1)
                    detail[k] = v
        elif info_line.startswith(b"-"):
            detail["auth"] = "required"
        return {"type": "redis", "version": version, "detail": detail or {"reply": "pong"}}
    except (OSError, TimeoutError, asyncio.IncompleteReadError):
        return None


async def fingerprint_postgresql(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> dict | None:
    """PG SSLRequest：len=8 + 80877103 → 应答单字节 'N'（明文拒绝）或 'S'。"""
    writer.write((8).to_bytes(4, "big") + (80877103).to_bytes(4, "big"))
    await writer.drain()
    try:
        resp = await _read_exactly(reader, 1)
    except (OSError, TimeoutError, asyncio.IncompleteReadError):
        return None
    if resp in (b"N", b"S"):
        return {"type": "postgresql", "version": None, "detail": {"ssl": resp.decode()}}
    return None


async def fingerprint_mongodb(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> dict | None:
    """MongoDB OP_MSG hello：应答 16 字节消息头 opcode=2013（不解析 BSON，识别即可）。"""
    import struct

    # BSON 文档 {"hello": 1}：int32 总长 + (0x10 "hello"\\0 int32(1)) + 0x00 结尾
    element = b"\x10hello\x00" + struct.pack("<i", 1)
    doc = struct.pack("<i", 4 + len(element) + 1) + element + b"\x00"
    msg_body = b"\x00\x00\x00\x00" + b"\x00" + doc  # flagBits=0 + section kind 0 + 文档
    header = struct.pack("<iiii", 16 + len(msg_body), 1, 0, 2013)
    writer.write(header + msg_body)
    await writer.drain()
    try:
        head = await _read_exactly(reader, 16)
        opcode = struct.unpack("<i", head[12:16])[0]
    except (OSError, TimeoutError, asyncio.IncompleteReadError):
        return None
    if opcode in (2013, 2012, 2007):  # OP_MSG / OP_COMMANDReply / OP_REPLY
        return {"type": "mongodb", "version": None, "detail": {"wire": opcode}}
    return None


async def _http_get(url: str, timeout: float = HTTP_TIMEOUT) -> httpx.Response | None:
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            return await client.get(url)
    except Exception:
        return None


async def fingerprint_minio(host: str, port: int) -> dict | None:
    resp = await _http_get(f"http://{host}:{port}/minio/health/live")
    if resp is None or resp.status_code != 200:
        return None
    return {"type": "minio", "version": None,
            "detail": {"server": resp.headers.get("server", ""), "console": port == 9001}}


async def fingerprint_elasticsearch(host: str, port: int) -> dict | None:
    resp = await _http_get(f"http://{host}:{port}/")
    if resp is None or resp.status_code != 200:
        return None
    try:
        version = resp.json().get("version", {}).get("number")
    except ValueError:
        return None
    return {"type": "elasticsearch", "version": version, "detail": {}}


async def fingerprint_memcached(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> dict | None:
    writer.write(b"version\r\n")
    await writer.drain()
    try:
        line = await asyncio.wait_for(reader.readline(), CONNECT_TIMEOUT)
    except (OSError, TimeoutError):
        return None
    if line.startswith(b"VERSION "):
        version = line.split(b" ", 1)[1].strip().decode()
        return {"type": "memcached", "version": version, "detail": {}}
    return None


async def fingerprint_etcd(host: str, port: int) -> dict | None:
    resp = await _http_get(f"http://{host}:{port}/health")
    if resp is None or resp.status_code != 200:
        return None
    try:
        healthy = resp.json().get("health")
    except ValueError:
        return None
    return {"type": "etcd", "version": None, "detail": {"health": healthy}}


async def fingerprint_clickhouse(host: str, port: int) -> dict | None:
    resp = await _http_get(f"http://{host}:{port}/ping")
    if resp is None or "Ok" not in resp.text[:16]:
        return None
    ver = await _http_get(f"http://{host}:{port}/?query=SELECT%20version()")
    version = ver.text.strip() if ver is not None and ver.status_code == 200 else None
    return {"type": "clickhouse", "version": version, "detail": {}}


async def sniff_unknown(host: str, port: int) -> dict | None:
    """未知端口的服务嗅探（M20-1 扩展：非默认端口的自建服务，如 MySQL@3309）。

    依服务端行为分派：MySQL greeting（服务端先发）→ 发 PING 看响应——
    有 RESP 文本行 = Redis；完全静默 = PG 候选（发 SSLRequest，要求单字节
    N/S 应答）；有 HTTP 风格文本行 = 跳过 PG，直接 HTTP 族探测。
    （110 实测修正：HTTP 服务器对 SSLRequest 可能回单个 "S" 字节，造成
    postgresql 误报——文本行门控消除该路径。）
    """
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), CONNECT_TIMEOUT
        )
    except (OSError, TimeoutError):
        return None

    async def _readline() -> bytes | None:
        try:
            return await asyncio.wait_for(reader.readline(), CONNECT_TIMEOUT)
        except (OSError, TimeoutError, asyncio.IncompleteReadError):
            return None

    try:
        # 1) MySQL：服务端先发 greeting
        fp = await fingerprint_mysql(reader)
        if fp:
            return fp
        # 2) Redis：PING → RESP 文本行（+PONG / -NOAUTH / $bulk）
        writer.write(b"PING\r\n")
        await writer.drain()
        line = await _readline()
        if line and (line.startswith(b"+") or line.startswith(b"$") or line.startswith(b"-")):
            detail: dict = {}
            version = None
            if line.startswith(b"$"):
                try:
                    body = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), CONNECT_TIMEOUT)
                    for row in body.decode("utf-8", "replace").splitlines():
                        if row.startswith("redis_version:"):
                            version = row.split(":", 1)[1]
                except (OSError, TimeoutError, asyncio.IncompleteReadError):
                    pass
            elif line.startswith(b"-"):
                detail["auth"] = "required"
            return {"type": "redis", "version": version, "detail": detail or {"reply": "pong"}}
        # 3) 完全静默 → PG 候选（真实 PG 对 PING 不响应，等 SSLRequest）
        if line is None:
            fp = await fingerprint_postgresql(reader, writer)
            if fp:
                return fp
    except (OSError, TimeoutError):
        return None
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (OSError, TimeoutError):
            pass
    # 4) HTTP 族（MinIO health / ES / etcd /health / ClickHouse /ping）
    http_probes = (
        fingerprint_minio, fingerprint_elasticsearch, fingerprint_etcd, fingerprint_clickhouse,
    )
    for probe in http_probes:
        fp = await probe(host, port)
        if fp:
            return fp
    return None


async def probe_service(host: str, port: int, sniff_extra: bool = False) -> dict | None:
    """单 host:port 指纹探测：TCP 连接 → 按端口分派协议握手；失败返回 None。

    sniff_extra=True 时对端口字典之外的自定义端口做通用协议嗅探。
    """
    stype = DB_PORTS.get(port)
    if stype is None:
        if sniff_extra:
            started = time.perf_counter()
            fp = await sniff_unknown(host, port)
            if fp:
                fp["latency_ms"] = int((time.perf_counter() - started) * 1000)
            return fp
        return None
    started = time.perf_counter()
    if stype in ("minio", "elasticsearch", "etcd", "clickhouse"):
        http_probes = {
            "minio": fingerprint_minio,
            "elasticsearch": fingerprint_elasticsearch,
            "etcd": fingerprint_etcd,
            "clickhouse": fingerprint_clickhouse,
        }
        fp = await http_probes[stype](host, port)
        latency = int((time.perf_counter() - started) * 1000)
        if fp:
            fp["latency_ms"] = latency
        return fp
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), CONNECT_TIMEOUT
        )
    except (OSError, TimeoutError):
        return None
    try:
        if stype == "mysql":
            fp = await fingerprint_mysql(reader)
        elif stype == "redis":
            fp = await fingerprint_redis(reader, writer)
        elif stype == "postgresql":
            fp = await fingerprint_postgresql(reader, writer)
        elif stype == "mongodb":
            fp = await fingerprint_mongodb(reader, writer)
        else:  # memcached
            fp = await fingerprint_memcached(reader, writer)
        latency = int((time.perf_counter() - started) * 1000)
        if fp:
            fp["latency_ms"] = latency
        return fp
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (OSError, TimeoutError):
            pass


# ---- 扫描任务 ----

_current: dict | None = None


def db_scan_status() -> dict | None:
    return dict(_current) if _current else None


async def _run_db_scan(run_id: int, cidrs: list[str], extra_ports: list[int] | None = None) -> None:
    global _current
    ports = list(DB_PORTS) + [p for p in (extra_ports or []) if p not in DB_PORTS]
    targets: list[tuple[str, int, bool]] = []
    for cidr in cidrs:
        for host in _hosts_of(cidr):
            for port in ports:
                targets.append((host, port, port not in DB_PORTS))
    total = max(len(targets), 1)
    sem = asyncio.Semaphore(96)

    async def _one(host: str, port: int, sniff: bool):
        async with sem:
            return host, port, await probe_service(host, port, sniff_extra=sniff)

    results = []
    done = 0
    batch = 256
    async with SessionLocal() as session:
        try:
            for i in range(0, len(targets), batch):
                part = await asyncio.gather(*(_one(h, p, s) for h, p, s in targets[i:i + batch]))
                results.extend(r for r in part if r[2])
                done += len(part)
                run = await session.get(LanScanRun, run_id)
                run.progress = min(99, done * 100 // total)
                run.found = len(results)
                await session.commit()
            now = datetime.utcnow()
            # 与既有服务合并 upsert（host+port 唯一）
            existing = {
                (s.host, s.port): s
                for s in (await session.execute(select(LanDbService))).scalars().all()
            }
            new_count = 0
            for host, port, fp in results:
                svc = existing.get((host, port))
                if svc is None:
                    cred_id = await _match_credential(session, host, port)
                    session.add(LanDbService(
                        host=host, port=port, service_type=fp["type"], version=fp.get("version"),
                        fingerprint=json.dumps(fp.get("detail", {}), ensure_ascii=False),
                        credential_id=cred_id, state="up", latency_ms=fp.get("latency_ms"),
                        online=1, first_seen_at=now, last_seen_at=now,
                    ))
                    new_count += 1
                else:
                    if fp.get("type") != "unknown":
                        svc.service_type = fp["type"]
                    if fp.get("version"):
                        svc.version = fp["version"]
                    svc.state = "up"
                    svc.latency_ms = fp.get("latency_ms")
                    svc.online = 1
                    svc.last_seen_at = now
                    if svc.credential_id is None:
                        svc.credential_id = await _match_credential(session, host, port)
            # 本轮未命中的既有服务 → 探活一次（up/down 翻转通知）
            seen = {(h, p) for h, p, _ in results}
            for (host, port), svc in existing.items():
                if (host, port) in seen:
                    continue
                fp = await probe_service(host, port)
                if fp:
                    svc.state, svc.online, svc.last_seen_at = "up", 1, now
                    svc.latency_ms = fp.get("latency_ms")
                    results.append((host, port, fp))
                else:
                    if svc.state == "up":
                        await _dispatch_state(session, svc, "down")
                    svc.state, svc.online = "down", 0
                    svc.last_seen_at = now
            run = await session.get(LanScanRun, run_id)
            run.status, run.progress, run.found = "done", 100, len(results)
            run.new_count, run.gone_count = new_count, 0
            run.finished_at = now
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            run = await session.get(LanScanRun, run_id)
            if run:
                run.status, run.message = "failed", str(exc)[:300]
                run.finished_at = datetime.utcnow()
                await session.commit()
        finally:
            _current = None


async def _match_credential(session: AsyncSession, host: str, port: int) -> int | None:
    from app.models.lan import DbCredential

    cred = (
        await session.execute(
            select(DbCredential)
            .where(DbCredential.host == host, DbCredential.port == port, DbCredential.enabled == 1)
            .limit(1)
        )
    ).scalar_one_or_none()
    return cred.id if cred else None


async def _dispatch_state(session: AsyncSession, svc: LanDbService, state: str) -> None:
    from app.services import wsbus
    from app.services.notify import dispatch

    word = "恢复" if state == "up" else "不可达"
    await dispatch(
        session, event=f"db_service_{state}", source="db",
        title=f"数据库服务{word} {svc.host}:{svc.port}（{svc.service_type}）",
        body="", level="info" if state == "up" else "warn",
    )
    await wsbus.broadcast({"type": "db_service", "data": {
        "service_id": svc.id, "service_type": svc.service_type, "state": state,
    }})


async def start_db_scan(
    session: AsyncSession, cidrs: list[str] | None = None,
    hint_ips: list[str] | None = None,
) -> LanScanRun:
    """触发数据库指纹扫描；设备扫描与 DB 扫描共用互斥位（一个时刻一个任务）。

    网段缺省优先级与设备扫描一致（设置 → Portal 访问地址派生 → 容器网关）。
    """
    global _current
    if _current is not None or scan_status() is not None:
        raise LookupError("scan busy")
    cfg = await get_lan_config(session)
    target = cidrs if cidrs else (cfg["scan_cidrs"] or [])
    if not target:
        # 无配置网段：沿用设备扫描的自动识别（含 Portal 访问地址提示）
        from app.services.lan_scan import auto_cidrs

        target = auto_cidrs(hint_ips)
    target = validate_scan_cidrs(target, cfg["extra_cidrs"])
    extra = cfg.get("db_extra_ports") or []
    port_count = len(DB_PORTS) + len([p for p in extra if p not in DB_PORTS])
    run = LanScanRun(kind="db", cidrs=json.dumps(target), status="running",
                     total=port_count * len({h for c in target for h in _hosts_of(c)}))
    session.add(run)
    await session.commit()
    _current = {"run_id": run.id, "kind": "db"}
    asyncio.get_running_loop().create_task(_run_db_scan(run.id, target, extra))
    return run


async def probe_and_upsert(
    session: AsyncSession, host: str, port: int
) -> tuple[LanDbService, bool]:
    """手动添加服务（M20 扩展）：立即指纹探测并 upsert；探测失败也入库
    （state=down/unknown），便于先配凭据、服务上线后由定时探活接续。"""
    fp = await probe_service(host, port, sniff_extra=True)
    now = datetime.utcnow()
    svc = (
        await session.execute(
            select(LanDbService).where(LanDbService.host == host, LanDbService.port == port)
        )
    ).scalar_one_or_none()
    created = svc is None
    if created:
        svc = LanDbService(host=host, port=port, first_seen_at=now)
        session.add(svc)
    if fp:
        if fp.get("type") != "unknown":
            svc.service_type = fp["type"]
        if fp.get("version"):
            svc.version = fp["version"]
        svc.fingerprint = json.dumps(fp.get("detail", {}), ensure_ascii=False)
        svc.state, svc.online, svc.latency_ms = "up", 1, fp.get("latency_ms")
    else:
        svc.state, svc.online = "down", 0
    svc.last_seen_at = now
    if svc.credential_id is None:
        svc.credential_id = await _match_credential(session, host, port)
    await session.commit()
    return svc, created


async def probe_due_services(session: AsyncSession) -> int:
    """定时探活（P27.6/M20-8）：全部已发现服务即时探测，状态翻转走通知。"""
    services = (await session.execute(select(LanDbService))).scalars().all()
    flipped = 0
    for svc in services:
        fp = await probe_service(svc.host, svc.port)
        new_state = "up" if fp else "down"
        svc.last_seen_at = datetime.utcnow()
        svc.latency_ms = fp.get("latency_ms") if fp else None
        svc.online = 1 if fp else 0
        if fp and fp.get("version"):
            svc.version = fp["version"]
        if new_state != svc.state:
            svc.state = new_state
            flipped += 1
            await _dispatch_state(session, svc, new_state)
    if services:
        await session.commit()
    return flipped


__all__ = ["DB_PORTS", "probe_service", "start_db_scan", "db_scan_status", "probe_due_services"]
