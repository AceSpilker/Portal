"""数据库只读查看器（M20-4/5/6；dev-plan P27.3~P27.5；api-spec §4.15）。

只读策略（安全边界，见 api-spec §4.15 注）：
- 全部为服务端白名单固定查询，**不接受任意 SQL/命令输入**——
  MySQL 仅 SHOW GLOBAL STATUS / SHOW VARIABLES / information_schema / SHOW PROCESSLIST；
  Redis 仅 INFO / DBSIZE / SCAN / TYPE / TTL / MEMORY USAGE / GETRANGE / LRANGE /
  SMEMBERS / HGETALL / ZRANGE / SLOWLOG GET / CLIENT LIST（写命令不进代码路径）；
  MinIO 仅 GET（ListBuckets / ListObjectsV2 / health）与预签名 GET 下载；
- 连接短连接（按请求建立，5s 超时），失败抛 ViewerError（API 层转 4004）；
- MinIO 走标准库 SigV4 手工签名（不引入 minio SDK）。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

CONNECT_TIMEOUT = 5.0
HTTP_TIMEOUT = 6.0
S3_REGION = "us-east-1"  # MinIO 单机默认签名区
_EMPTY_SHA = hashlib.sha256(b"").hexdigest()


class ViewerError(Exception):
    """查看器连接/查询失败（API 层转 4004 + 错误摘要）。"""


# ===================== AWS SigV4 手工签名（标准库实现） =====================

def _amz_date() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _signing_key(secret: str, date: str, region: str, service: str) -> bytes:
    k = _hmac(f"AWS4{secret}".encode(), date)
    k = _hmac(k, region)
    k = _hmac(k, service)
    return _hmac(k, "aws4_request")


def _canonical_query(params: list[tuple[str, str]]) -> str:
    return "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in sorted(params))


def sigv4_header(
    method: str, endpoint: str, access_key: str, secret_key: str,
    canonical_uri: str = "/", query: list[tuple[str, str]] | None = None,
    region: str = S3_REGION, service: str = "s3",
) -> dict[str, str]:
    """生成 Authorization 头（GET 空载荷）。endpoint 形如 host:port。"""
    amz_dt, date = _amz_date()
    q = _canonical_query(query or [])
    canonical = "\n".join([
        method, canonical_uri, q,
        f"host:{endpoint}",  # 已签名头仅有 host
        "", "host",
        _EMPTY_SHA,
    ])
    scope = f"{date}/{region}/{service}/aws4_request"
    canonical_hash = hashlib.sha256(canonical.encode()).hexdigest()
    sts = "\n".join(["AWS4-HMAC-SHA256", amz_dt, scope, canonical_hash])
    sig = hmac.new(
        _signing_key(secret_key, date, region, service), sts.encode(), hashlib.sha256
    ).hexdigest()
    cred = f"{access_key}/{scope}"
    return {
        "x-amz-date": amz_dt,
        "x-amz-content-sha256": _EMPTY_SHA,
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={cred}, SignedHeaders=host, Signature={sig}"
        ),
    }


def presign_get_url(
    endpoint: str, access_key: str, secret_key: str, bucket: str, key: str,
    expires: int = 300, scheme: str = "http", region: str = S3_REGION,
) -> str:
    """预签名 GET 下载 URL（短时效只读，secret 不落 URL）。"""
    amz_dt, date = _amz_date()
    canonical_uri = f"/{quote(bucket)}/{quote(key, safe='/')}"
    params = [
        ("X-Amz-Algorithm", "AWS4-HMAC-SHA256"),
        ("X-Amz-Credential", f"{access_key}/{date}/{region}/s3/aws4_request"),
        ("X-Amz-Date", amz_dt),
        ("X-Amz-Expires", str(expires)),
        ("X-Amz-SignedHeaders", "host"),
    ]
    q = _canonical_query(params)
    canonical = f"GET\n{canonical_uri}\n{q}\nhost:{endpoint}\n\nhost\n{_EMPTY_SHA}"
    scope = f"{date}/{region}/s3/aws4_request"
    sts = f"AWS4-HMAC-SHA256\n{amz_dt}\n{scope}\n{hashlib.sha256(canonical.encode()).hexdigest()}"
    sig = hmac.new(
        _signing_key(secret_key, date, region, "s3"), sts.encode(), hashlib.sha256
    ).hexdigest()
    return f"{scheme}://{endpoint}{canonical_uri}?{q}&X-Amz-Signature={sig}"


# ===================== MySQL 只读查看器（aiomysql） =====================

MYSQL_STATUS_KEYS = (
    "Uptime", "Threads_connected", "Threads_running", "Questions", "Slow_queries",
    "Bytes_received", "Bytes_sent", "Connections", "Aborted_clients", "Max_used_connections",
)


async def _mysql_connect(cred) -> object:
    import aiomysql

    extra = json.loads(cred.extra or "{}")
    try:
        return await asyncio.wait_for(
            aiomysql.connect(
                host=cred.host, port=cred.port, user=cred.username,
                password=_cred_secret(cred), db=extra.get("database") or None,
                connect_timeout=CONNECT_TIMEOUT,
            ),
            CONNECT_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        raise ViewerError(f"MySQL 连接失败：{str(exc)[:200]}") from exc


def _cred_secret(cred) -> str:
    from app.core.secret_box import decrypt_secret

    return decrypt_secret(cred.secret or "")


async def _mysql_fetch(cred, sql: str) -> list[dict]:
    """执行白名单查询并返回 dict 行（列名小写）。"""
    import aiomysql

    conn = await _mysql_connect(cred)
    try:
        async with conn.cursor(aiomysql.cursors.DictCursor) as cur:
            await cur.execute(sql)
            return list(await cur.fetchall())
    except Exception as exc:  # noqa: BLE001
        raise ViewerError(f"MySQL 查询失败：{str(exc)[:200]}") from exc
    finally:
        conn.close()


async def mysql_overview(cred) -> dict:
    rows = await _mysql_fetch(cred, "SHOW GLOBAL STATUS")
    status = {r["Variable_name"]: r["Value"] for r in rows}
    variables = {r["Variable_name"]: r["Value"] for r in await _mysql_fetch(cred, "SHOW VARIABLES")}

    def _int(key: str) -> int:
        try:
            return int(status.get(key, 0))
        except (TypeError, ValueError):
            return 0

    uptime = _int("Uptime")
    return {
        "version": variables.get("version", ""),
        "uptime_seconds": uptime,
        "threads_connected": _int("Threads_connected"),
        "threads_running": _int("Threads_running"),
        "connections_total": _int("Connections"),
        "max_used_connections": _int("Max_used_connections"),
        "slow_queries": _int("Slow_queries"),
        "bytes_received": _int("Bytes_received"),
        "bytes_sent": _int("Bytes_sent"),
        "qps_avg": round(_int("Questions") / uptime, 2) if uptime else 0,
        "hostname": variables.get("hostname", ""),
        "datadir": variables.get("datadir", ""),
    }


async def mysql_variables(cred, q: str = "") -> dict:
    rows = await _mysql_fetch(cred, "SHOW VARIABLES")
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in str(r["Variable_name"]).lower()]
    return {"total": len(rows), "items": rows[:200]}


async def mysql_schemas(cred, schema: str = "", page: int = 1, page_size: int = 50) -> dict:
    where = ""
    if schema:
        safe = re.sub(r"[^\w%]", "", schema[:64])  # 防注入：仅字母数字下划线百分号
        if safe:
            where = f" WHERE table_schema LIKE '%{safe}%'"
    total = await _mysql_fetch(
        cred, f"SELECT COUNT(*) AS n FROM information_schema.tables{where}"
    )
    offset = max(0, (page - 1) * page_size)
    rows = await _mysql_fetch(
        cred,
        f"SELECT table_schema, table_name, engine, table_rows,"
        f" ROUND((data_length+index_length)/1024/1024, 2) AS size_mb"
        f" FROM information_schema.tables{where}"
        f" ORDER BY table_schema, size_mb DESC LIMIT {int(page_size)} OFFSET {offset}",
    )
    return {"total": int(total[0]["n"]), "page": page, "page_size": page_size, "items": rows}


async def mysql_processlist(cred) -> dict:
    rows = await _mysql_fetch(cred, "SHOW PROCESSLIST")
    for r in rows:
        r["Info"] = str(r.get("Info") or "")[:200]
    return {"items": rows}


# ---- MySQL 数据浏览（M20-4 扩展：库 → 表 → 行；用户核心诉求） ----

_IDENT_RE = re.compile(r"^[A-Za-z0-9_$]+$")  # 标识符白名单：拒绝引号/分号/注释等
_VALUE_LIMIT = 200  # 单元格显示截断
_VALUE_BYTES_LIMIT = 4000  # 单单元格读取字节上限（防大字段拖爆）


def _quote_ident(name: str) -> str:
    """表/库名白名单校验 + 反引号引用（只允许字母数字下划线 $，杜绝注入）。"""
    name = (name or "").strip()
    if not name or len(name) > 64 or not _IDENT_RE.match(name):
        raise ViewerError(f"非法标识符：{name[:64]}")
    return f"`{name}`"


async def mysql_table_rows(
    cred, schema: str, table: str, page: int = 1, page_size: int = 50
) -> dict:
    """表数据分页：SELECT *（白名单标识符 + 参数化分页；单元格截断防大字段）。

    固定查询模板，用户仅能选择 库名/表名（标识符白名单），无任意 SQL 输入。
    """
    qschema = _quote_ident(schema)
    qtable = _quote_ident(table)
    page_size = max(1, min(200, page_size))
    offset = max(0, (max(1, page) - 1) * page_size)
    total_rows = await _mysql_fetch(
        cred, f"SELECT COUNT(*) AS n FROM {qschema}.{qtable}"
    )
    rows = await _mysql_fetch(
        cred,
        f"SELECT * FROM {qschema}.{qtable} LIMIT {page_size} OFFSET {offset}",
    )
    items = []
    for row in rows:
        items.append({
            k: _cell_preview(v) for k, v in row.items()
        })
    return {
        "schema": schema, "table": table, "page": max(1, page), "page_size": page_size,
        "total": int(total_rows[0]["n"]) if total_rows else 0,
        "columns": [k for k in (items[0].keys() if items else [])],
        "items": items,
    }


def _cell_preview(value) -> str:
    """单元格预览：bytes → hex 摘要；其余 str() 截断 200 字符。"""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return f"<binary {len(raw)}B> {raw[:48].hex()}{'…' if len(raw) > 48 else ''}"
    text = str(value)
    return text[:_VALUE_LIMIT] + ("…" if len(text) > _VALUE_LIMIT else "")


# ===================== Redis 只读查看器（redis.asyncio） =====================

REDIS_INFO_SECTIONS = ("server", "clients", "memory", "persistence", "stats", "replication")


async def _redis_client(cred):
    import redis.asyncio as aioredis

    extra = json.loads(cred.extra or "{}")
    return aioredis.Redis(
        host=cred.host, port=cred.port, password=_cred_secret(cred) or None,
        db=int(extra.get("db") or 0), socket_timeout=CONNECT_TIMEOUT,
        socket_connect_timeout=CONNECT_TIMEOUT,
    )


async def redis_info(cred) -> dict:
    client = await _redis_client(cred)
    try:
        sections = {}
        for sec in REDIS_INFO_SECTIONS:
            try:
                sections[sec] = await client.info(sec)
            except Exception:  # noqa: BLE001 单段失败不影响整体
                sections[sec] = {}
        dbsize = await client.dbsize()
        return {"sections": sections, "dbsize": dbsize}
    except Exception as exc:  # noqa: BLE001
        raise ViewerError(f"Redis 连接失败：{str(exc)[:200]}") from exc
    finally:
        await client.aclose()


async def redis_keys(cred, db: int = 0, cursor: int = 0, match: str = "", count: int = 100) -> dict:
    client = await _redis_client(cred)
    try:
        if db:
            await client.execute_command("SELECT", int(db))  # 白名单内仅此处用整数参数
        next_cursor, keys = await client.scan(cursor=cursor, match=match or "*", count=count)
        items: list[dict] = []
        if keys:
            pipe = client.pipeline(transaction=False)
            for key in keys[: count]:
                pipe.type(key)
                pipe.ttl(key)
            results = await pipe.execute()
            for i, key in enumerate(keys[: count]):
                ktype = results[i * 2]
                ktype = ktype.decode() if isinstance(ktype, bytes) else str(ktype)
                items.append({
                    "key": key.decode("utf-8", "replace") if isinstance(key, bytes) else str(key),
                    "type": ktype,
                    "ttl": results[i * 2 + 1],
                })
        return {"cursor": int(next_cursor), "items": items}
    except ViewerError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ViewerError(f"Redis 键浏览失败：{str(exc)[:200]}") from exc
    finally:
        await client.aclose()


_VALUE_PREVIEW_LIMIT = 4096  # 值预览截断（字节）
_COLLECTION_LIMIT = 100  # 集合类条目上限


def _preview_bytes(raw: bytes) -> dict:
    """值预览：文本直出；含 NUL 或替换符密集 → hex 预览 + binary 标记。"""
    if b"\x00" in raw:
        return {"binary": True, "preview": raw[:64].hex()}
    text = raw.decode("utf-8", "replace")
    if text[:256].count("\ufffd") > 8:
        return {"binary": True, "preview": raw[:64].hex()}
    return {"binary": False, "preview": text[:_VALUE_PREVIEW_LIMIT],
            "truncated": len(text) > _VALUE_PREVIEW_LIMIT}


async def redis_key_detail(cred, key: str, db: int = 0) -> dict:
    client = await _redis_client(cred)
    try:
        if db:
            await client.execute_command("SELECT", int(db))
        raw_key = key.encode("utf-8", "replace")
        ktype = await client.type(raw_key)
        ktype = ktype.decode() if isinstance(ktype, bytes) else str(ktype)
        if ktype == "none":
            raise ViewerError("键不存在")
        ttl = await client.ttl(raw_key)
        out: dict = {"key": key, "type": ktype, "ttl": ttl, "db": db}
        try:
            out["memory_bytes"] = await client.memory_usage(raw_key)
        except Exception:  # noqa: BLE001 老版本可能禁用
            out["memory_bytes"] = None
        if ktype == "string":
            raw = await client.getrange(raw_key, 0, _VALUE_PREVIEW_LIMIT + 1)
            out.update(_preview_bytes(raw))
            out["size_bytes"] = out["memory_bytes"]
        elif ktype == "list":
            rows = await client.lrange(raw_key, 0, _COLLECTION_LIMIT - 1)
            out["items"] = [_preview_bytes(v) for v in rows]
            out["size_bytes"] = await client.llen(raw_key)
        elif ktype == "hash":
            rows = await client.hgetall(raw_key)
            entries = list(rows.items())[:_COLLECTION_LIMIT]
            out["items"] = [
                {"field": f.decode("utf-8", "replace"), **_preview_bytes(v)} for f, v in entries
            ]
            out["size_bytes"] = await client.hlen(raw_key)
        elif ktype == "set":
            rows = await client.srandmember(raw_key, _COLLECTION_LIMIT) or []
            out["items"] = [_preview_bytes(v) for v in rows]
            out["size_bytes"] = await client.scard(raw_key)
        elif ktype == "zset":
            rows = await client.zrange(raw_key, 0, _COLLECTION_LIMIT - 1, withscores=True)
            out["items"] = [
                {"member": m.decode("utf-8", "replace") if isinstance(m, bytes) else str(m),
                 "score": s} for m, s in rows
            ]
            out["size_bytes"] = await client.zcard(raw_key)
        else:
            out["items"] = []
            out["size_bytes"] = out["memory_bytes"]
        return out
    except ViewerError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ViewerError(f"Redis 键详情失败：{str(exc)[:200]}") from exc
    finally:
        await client.aclose()


async def redis_slowlog(cred) -> dict:
    client = await _redis_client(cred)
    try:
        rows = await client.slowlog_get(20)
        items = []
        for r in rows or []:
            cmd = r.get("command") or r.get("command_stats") or []
            if isinstance(cmd, (list, tuple)):
                cmd = " ".join(
                c.decode("utf-8", "replace") if isinstance(c, bytes) else str(c)
                for c in cmd[:8]
            )
            items.append({
                "id": r.get("id"),
                "started_at": r.get("start_time"),
                "duration_us": r.get("duration") or r.get("duration_us"),
                "command": str(cmd)[:300],
            })
        return {"items": items}
    except Exception as exc:  # noqa: BLE001
        raise ViewerError(f"Redis 慢日志失败：{str(exc)[:200]}") from exc
    finally:
        await client.aclose()


async def redis_clients(cred) -> dict:
    client = await _redis_client(cred)
    try:
        rows = await client.client_list()
        items = [
            {k: r.get(k) for k in ("id", "addr", "name", "db", "cmd", "idle", "age")}
            for r in rows or []
        ]
        return {"items": items}
    except Exception as exc:  # noqa: BLE001
        raise ViewerError(f"Redis 客户端列表失败：{str(exc)[:200]}") from exc
    finally:
        await client.aclose()


# ===================== MinIO 只读查看器（httpx + SigV4） =====================

def _minio_base(cred) -> tuple[str, str, str, str, bool]:
    """返回 (endpoint, access_key, secret_key, region, use_ssl)。"""
    extra = json.loads(cred.extra or "{}")
    return (
        f"{cred.host}:{cred.port}", cred.username, _cred_secret(cred),
        str(extra.get("region") or S3_REGION), bool(extra.get("use_ssl")),
    )


async def _minio_get(cred, path: str, query: list[tuple[str, str]] | None = None) -> httpx.Response:
    endpoint, ak, sk, region, use_ssl = _minio_base(cred)
    scheme = "https" if use_ssl else "http"
    headers = sigv4_header("GET", endpoint, ak, sk, path, query, region=region)
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{scheme}://{endpoint}{path}", params=dict(query or {}), headers=headers
            )
    except Exception as exc:  # noqa: BLE001
        raise ViewerError(f"MinIO 请求失败：{str(exc)[:200]}") from exc
    if resp.status_code == 403:
        raise ViewerError("MinIO 认证失败（AccessKey/SecretKey 不正确）")
    if resp.status_code >= 500:
        raise ViewerError(f"MinIO 服务错误 HTTP {resp.status_code}")
    return resp


def _xml_findall(root: ET.Element, name: str) -> list[ET.Element]:
    return [el for el in root.iter() if el.tag.split("}")[-1] == name]


def _xml_text(root: ET.Element, name: str) -> str:
    for el in root.iter():
        if el.tag.split("}")[-1] == name and el.text is not None:
            return el.text
    return ""


async def minio_overview(cred) -> dict:
    endpoint = _minio_base(cred)[0]
    use_ssl = _minio_base(cred)[4]
    scheme = "https" if use_ssl else "http"
    healthy = None
    server_header = ""
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(f"{scheme}://{endpoint}/minio/health/live")
            healthy = resp.status_code == 200
            server_header = resp.headers.get("server", "")
    except Exception:  # noqa: BLE001
        healthy = False
    buckets = await minio_buckets(cred)
    return {
        "healthy": healthy, "server": server_header,
        "bucket_count": len(buckets["items"]),
        "object_count": sum(b["object_count"] for b in buckets["items"]),
        "total_size_bytes": sum(b["size_bytes"] for b in buckets["items"]),
    }


async def minio_buckets(cred) -> dict:
    resp = await _minio_get(cred, "/")
    if resp.status_code != 200:
        raise ViewerError(f"ListBuckets 失败 HTTP {resp.status_code}")
    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as exc:
        raise ViewerError(f"ListBuckets 响应解析失败：{exc}") from exc
    items = []
    for bucket in _xml_findall(root, "Bucket"):
        items.append({
            "name": _xml_text(bucket, "Name"),
            "created_at": _xml_text(bucket, "CreationDate"),
            "object_count": 0,
            "size_bytes": 0,
        })
    # 每桶对象数与前 1000 对象累计大小（家庭规模足够，近似值标注 truncated）
    for item in items:
        listing = await _list_objects(cred, item["name"], "", 1000)
        item["object_count"] = listing["key_count"]
        item["size_bytes"] = listing["size_sum"]
        item["truncated"] = listing["truncated"]
    return {"items": items}


async def _list_objects(cred, bucket: str, prefix: str, limit: int) -> dict:
    query: list[tuple[str, str]] = [("list-type", "2"), ("max-keys", str(limit))]
    if prefix:
        query.append(("prefix", prefix))
    path = f"/{quote(bucket, safe='')}/"
    resp = await _minio_get(cred, path, query)
    if resp.status_code != 200:
        return {"key_count": 0, "size_sum": 0, "truncated": False, "objects": []}
    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError:
        return {"key_count": 0, "size_sum": 0, "truncated": False, "objects": []}
    objects = []
    size_sum = 0
    for c in _xml_findall(root, "Contents"):
        size = int(_xml_text(c, "Size") or 0)
        size_sum += size
        objects.append({
            "key": _xml_text(c, "Key"),
            "size": size,
            "etag": _xml_text(c, "ETag").strip('"'),
            "last_modified": _xml_text(c, "LastModified"),
        })
    truncated = _xml_text(root, "IsTruncated").lower() == "true"
    return {"key_count": len(objects), "size_sum": size_sum, "truncated": truncated,
            "objects": objects}


async def minio_objects(
    cred, bucket: str, prefix: str = "", token: str = "", limit: int = 100
) -> dict:
    query: list[tuple[str, str]] = [
        ("list-type", "2"), ("max-keys", str(max(1, min(100, limit)))),
    ]
    if prefix:
        query.append(("prefix", prefix))
    if token:
        query.append(("continuation-token", token))
    path = f"/{quote(bucket, safe='')}/"
    resp = await _minio_get(cred, path, query)
    if resp.status_code != 200:
        raise ViewerError(f"ListObjects 失败 HTTP {resp.status_code}")
    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as exc:
        raise ViewerError(f"ListObjects 响应解析失败：{exc}") from exc
    objects = []
    for c in _xml_findall(root, "Contents"):
        objects.append({
            "key": _xml_text(c, "Key"),
            "size": int(_xml_text(c, "Size") or 0),
            "etag": _xml_text(c, "ETag").strip('"'),
            "last_modified": _xml_text(c, "LastModified"),
        })
    return {
        "bucket": bucket,
        "prefix": prefix,
        "objects": objects,
        "truncated": _xml_text(root, "IsTruncated").lower() == "true",
        "next_token": _xml_text(root, "NextContinuationToken"),
    }


def minio_object_url(cred, bucket: str, key: str, expires: int = 300) -> str:
    endpoint, ak, sk, region, use_ssl = _minio_base(cred)
    return presign_get_url(
        endpoint, ak, sk, bucket, key, expires=expires,
        scheme="https" if use_ssl else "http", region=region,
    )


# ===================== 凭据连通测试（27.2 POST /test） =====================

async def test_credential(cred) -> dict:
    """按类型真实握手：MySQL SELECT 1 / Redis PING+INFO / MinIO ListBuckets。"""
    try:
        if cred.service_type == "mysql":
            rows = await _mysql_fetch(cred, "SELECT 1 AS ok")
            return {"ok": bool(rows), "detail": "SELECT 1 成功"}
        if cred.service_type == "redis":
            info = await redis_info(cred)
            version = info["sections"]["server"].get("redis_version", "")
            return {"ok": True, "detail": f"PING/INFO 成功 v{version}"}
        if cred.service_type == "minio":
            buckets = await minio_buckets(cred)
            return {"ok": True, "detail": f"ListBuckets 成功（{len(buckets['items'])} 桶）"}
        return {"ok": False, "detail": f"未知类型 {cred.service_type}"}
    except ViewerError as exc:
        return {"ok": False, "detail": str(exc)[:200]}
