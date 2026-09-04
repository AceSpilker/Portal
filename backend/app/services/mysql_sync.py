"""MySQL 镜像同步引擎（M15-12；dev-plan P23；api-spec §4.12）。

数据策略：SQLite 为运行主库（业务读写全走它），客户机已有 MySQL 作为
灾备镜像——定时按表全量 upsert（主键 diff + 删除对齐），敏感表排除
（users/user_sessions/api_tokens/audit_logs/会话类）；MySQL 不可达不影响
本地功能，恢复后按退避自动补推。密码用 data/keys/sync.key（Fernet）加密
存储；未配置该文件时自动生成。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import Text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

# 同步范围：业务表（与 backup.collect_all 口径一致）；敏感/会话/大表排除
SYNC_TABLES: list[str] = [
    "categories",
    "apps",
    "app_urls",
    "network_profiles",
    "flows",
    "settings",
    "wol_targets",
    "notify_channels",
    "notify_rules",
]
# 每表主键（upsert 与删除对齐依据）
PRIMARY_KEYS: dict[str, str] = {
    "categories": "id",
    "apps": "id",
    "app_urls": "id",
    "network_profiles": "id",
    "flows": "id",
    "settings": "key",
    "wol_targets": "id",
    "notify_channels": "id",
    "notify_rules": "id",
}

_KEY_FILE = "keys/sync.key"
_RETRY_BASE_SEC = 60
_RETRY_MAX_SEC = 1800


# ---- 配置与密码加密 ----


def _key_path() -> Path:
    return Path(settings.data_dir) / _KEY_FILE


def _fernet():
    from cryptography.fernet import Fernet

    path = _key_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(Fernet.generate_key())
    return Fernet(path.read_bytes())


def encrypt_password(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode() if plain else ""


def decrypt_password(cipher: str) -> str:
    if not cipher:
        return ""
    try:
        return _fernet().decrypt(cipher.encode()).decode()
    except Exception:  # 密钥更换等：返回空（需重录密码）
        return ""


async def get_config(session: AsyncSession) -> dict:
    from app.models.setting import Setting

    cfg: dict = {}
    for key in ("mysql.host", "mysql.port", "mysql.user", "mysql.password",
                "mysql.database", "mysql.interval_min", "mysql.enabled"):
        row = await session.get(Setting, key)
        cfg[key.split(".", 1)[1]] = json.loads(row.value) if row else None
    cfg["password"] = decrypt_password(str(cfg.get("password") or ""))
    cfg["enabled"] = bool(cfg.get("enabled"))
    cfg["port"] = int(cfg.get("port") or 3306)
    cfg["interval_min"] = max(1, int(cfg.get("interval_min") or 30))
    return cfg


async def save_config(session: AsyncSession, body: dict) -> None:
    """写入 mysql.* 设置；密码传空 = 保持原值；传明文 = 加密落库。"""
    from app.models.setting import Setting

    mapping = {
        "host": str(body.get("host", ""))[:253],
        "port": int(body.get("port") or 3306),
        "user": str(body.get("user", ""))[:64],
        "database": str(body.get("database", ""))[:64],
        "interval_min": max(1, int(body.get("interval_min") or 30)),
        "enabled": bool(body.get("enabled", False)),
    }
    password = str(body.get("password", ""))
    if password:
        mapping["password"] = encrypt_password(password)
    for suffix, value in mapping.items():
        key = f"mysql.{suffix}"
        if suffix == "password" and not password:
            continue  # 空密码=保持原值
        await session.merge(Setting(key=key, value=json.dumps(value)))


# ---- 连接 ----


async def _connect(cfg: dict):
    """建立 aiomysql 连接；失败抛 OSError/aiomysql.Error。"""
    import aiomysql

    return await aiomysql.connect(
        host=cfg["host"], port=cfg["port"], user=cfg["user"],
        password=cfg["password"], db=cfg["database"], connect_timeout=5,
    )


async def test_connection(cfg: dict) -> dict:
    """连接测试（M23.2）：SELECT 1 + 服务器版本。"""
    conn = await _connect(cfg)
    try:
        async with conn.cursor() as cur:
            await cur.execute("SELECT VERSION()")
            version = (await cur.fetchone())[0]
        return {"ok": True, "server_version": str(version)}
    finally:
        conn.close()


# ---- 建表（M23.1：类型映射走 SQLAlchemy MySQL 方言）----


def ddl_statements() -> list[str]:
    """由 ORM 元数据生成 MySQL DDL（不含敏感表；本地验证类型映射）。"""
    from sqlalchemy.dialects import mysql
    from sqlalchemy.schema import CreateIndex, CreateTable

    from app.models import Base

    stmts: list[str] = []
    wanted = set(SYNC_TABLES)
    for table in Base.metadata.sorted_tables:
        if table.name not in wanted:
            continue
        ddl = str(CreateTable(table).compile(dialect=mysql.dialect())).strip() + ";"
        ddl = _fix_text_unique_keys(table, ddl)
        stmts.append(ddl)
        for index in table.indexes:
            stmts.append(str(CreateIndex(index).compile(dialect=mysql.dialect())).strip() + ";")
    return stmts


def _fix_text_unique_keys(table, ddl: str) -> str:
    """MySQL TEXT 列的两类不兼容修正（错误 1170/1101）：

    - UNIQUE 索引必须带前缀长度 → 改写为前缀 191（utf8mb4 下 764B，
      兼容 InnoDB 767B 旧限制）；
    - TEXT 列不允许字面 DEFAULT → 去掉 DEFAULT 子句（SQLite 侧语义由
      ORM default 兜底，SQLite 的 server_default 不迁移）。
    """
    for col in table.columns:
        if not isinstance(col.type, Text):
            continue
        if col.unique:
            ddl = re.sub(
                rf"UNIQUE \({col.name}\)",
                f"UNIQUE KEY ux_{table.name}_{col.name} ({col.name}(191))",
                ddl,
            )
        if col.server_default is not None:
            ddl = re.sub(
                rf"(`?{col.name}`?\s+TEXT[^,]*?)\s+DEFAULT\s+('(?:[^']|'')*'|\S+)",
                r"\1",
                ddl,
                flags=re.IGNORECASE,
            )
    return ddl


async def ensure_tables(cfg: dict) -> int:
    """在 MySQL 侧建缺失的表（幂等 CREATE TABLE IF NOT EXISTS）。"""
    import aiomysql

    conn = await _connect(cfg)
    created = 0
    try:
        async with conn.cursor() as cur:
            for ddl in ddl_statements():
                stmt = ddl.rstrip(";")
                stmt = stmt.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1)
                await cur.execute(stmt)
                created += 1
        await conn.commit()
    except aiomysql.Error:
        conn.close()
        raise
    return created


# ---- 推送引擎（M23.3/M23.4）----


def _quote(value) -> str:
    """SQL 字面量转义（本地受控数据，防御性处理）。"""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value).replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "")
    return f"'{s}'"


async def _push_table(conn, session: AsyncSession, table: str) -> int:
    """单表全量 upsert + 删除对齐。返回写入行数。"""
    from sqlalchemy import select as _sel

    from app.models import Base

    mapper = Base.metadata.tables[table]
    pk = PRIMARY_KEYS[table]
    rows = (await session.execute(_sel(mapper))).mappings().all()
    cols = list(mapper.columns.keys())
    col_list = ", ".join(f"`{c}`" for c in cols)

    async with conn.cursor() as cur:
        # upsert
        for row in rows:
            placeholders = ", ".join(["%s"] * len(cols))  # aiomysql 参数占位
            values = [
                json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                for v in (row[c] for c in cols)
            ]
            updates = ", ".join(f"`{c}`=VALUES(`{c}`)" for c in cols if c != pk)
            await cur.execute(
                f"INSERT INTO `{table}` ({col_list}) VALUES ({placeholders}) "
                f"ON DUPLICATE KEY UPDATE {updates}",
                values,
            )
        # 删除对齐：MySQL 中有而 SQLite 无的主键删除
        local_keys = [str(row[pk]) for row in rows]
        await cur.execute(f"SELECT `{pk}` FROM `{table}`")
        remote_keys = {str(r[0]) for r in await cur.fetchall()}
        removed = 0
        for rk in remote_keys - set(local_keys):
            await cur.execute(f"DELETE FROM `{table}` WHERE `{pk}` = %s", (rk,))
            removed += 1
    return len(rows) + removed


async def push_all(session: AsyncSession, force: bool = False) -> dict:
    """全量镜像推送（M23.3）：逐表 upsert+删除对齐，写 sync_state（M23.4）。

    - MySQL 不可达：全局状态 failed，本地不受影响；fail_count 退避重试；
    - force=True 忽略退避（「立即推送」按钮）。
    """
    from sqlalchemy import select as _sel

    from app.models.sync import SyncState

    cfg = await get_config(session)
    now = datetime.utcnow()
    states = {
        r.table_name: r
        for r in (await session.execute(_sel(SyncState))).scalars().all()
    }

    result = {
        "enabled": bool(cfg["enabled"] and cfg["host"]),
        "pushed": 0, "tables": 0, "skipped": False,
    }
    if not result["enabled"]:
        result["error"] = "disabled"
        return result

    # 全局退避判定：任一表未到期则跳过本轮（force 除外）
    if not force:
        for table in SYNC_TABLES:
            st = states.get(table)
            if st is None or st.status != "failed":
                continue
            backoff = min(_RETRY_BASE_SEC * (2 ** min(st.fail_count, 5)), _RETRY_MAX_SEC)
            if st.last_try_at and now < st.last_try_at + timedelta(seconds=backoff):
                result["skipped"] = True
                return result

    # 连接；不可达时全表记 failed（退避重试），本地不受影响
    conn = None
    errors: list[str] = []
    try:
        conn = await _connect(cfg)
    except Exception as exc:
        for table in SYNC_TABLES:
            st = states.get(table)
            if st is None:
                st = SyncState(table_name=table)
                session.add(st)
            st.status = "failed"
            st.fail_count = (st.fail_count or 0) + 1
            st.last_try_at = datetime.utcnow()
            st.message = str(exc)[:400]
        await session.commit()
        result["error"] = str(exc)[:300]
        return result

    try:
        # 幂等建表/建索引（CREATE IF NOT EXISTS；索引重复 1061、表已存在 1050 忽略）
        async with conn.cursor() as cur:
            for ddl in ddl_statements():
                stmt = ddl.rstrip(";").replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1)
                try:
                    await cur.execute(stmt)
                except Exception as exc:
                    code = getattr(exc, "args", [None])[0]
                    if code in (1050, 1061):
                        await conn.rollback()
                        continue
                    raise
        await conn.commit()

        for table in SYNC_TABLES:
            st = states.get(table)
            if st is None:
                st = SyncState(table_name=table)
                session.add(st)
            st.status = "running"
            st.last_try_at = datetime.utcnow()
            try:
                pushed = await _push_table(conn, session, table)
                await conn.commit()
                st.status = "ok"
                st.rows_pushed = pushed
                st.last_push_at = datetime.utcnow()
                st.fail_count = 0
                st.message = ""
                result["pushed"] += pushed
                result["tables"] += 1
            except Exception as exc:  # 单表失败继续
                await conn.rollback()
                st.status = "failed"
                st.fail_count = (st.fail_count or 0) + 1
                st.message = str(exc)[:400]
                errors.append(f"{table}: {exc}")
        await session.commit()
    finally:
        conn.close()
    if errors:
        result["error"] = "; ".join(errors)[:400]
    return result


async def sync_status(session: AsyncSession) -> dict:
    """同步状态视图（M23.4）：每表最近推送/行数/结果 + 总体健康。"""
    from sqlalchemy import select as _sel

    from app.models.sync import SyncState

    rows = (await session.execute(_sel(SyncState).order_by(SyncState.table_name))).scalars().all()
    cfg = await get_config(session)
    return {
        "enabled": bool(cfg["enabled"] and cfg["host"]),
        "host": cfg["host"],
        "database": cfg["database"],
        "interval_min": cfg["interval_min"],
        "tables": [
            {
                "table": r.table_name,
                "last_push_at": r.last_push_at.isoformat() + "Z" if r.last_push_at else None,
                "rows_pushed": r.rows_pushed,
                "status": r.status,
                "fail_count": r.fail_count,
                "message": r.message,
            }
            for r in rows
            if r.table_name in SYNC_TABLES
        ],
    }


# ---- 灾难恢复（M23.5）----


async def restore_from_mysql(session: AsyncSession) -> dict:
    """「从 MySQL 恢复到 SQLite」（M23.5）：读回同步范围数据 → restore_all。

    调用方负责覆盖确认与本地自动备份（端点层先 write_disk_backup）。
    """
    from app.services.backup import restore_all

    cfg = await get_config(session)
    conn = await _connect(cfg)
    data: dict = {"_export_version": 2}
    try:
        async with conn.cursor() as cur:
            for table in SYNC_TABLES:
                await cur.execute(f"SELECT * FROM `{table}`")
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, row)) for row in await cur.fetchall()]
                if table == "settings":
                    data[table] = rows
                else:
                    data.setdefault(table, rows)
    finally:
        conn.close()
    # app_urls 归并到 apps.urls
    urls_by_app: dict[int, list[dict]] = {}
    for u in data.get("app_urls", []):
        urls_by_app.setdefault(u["app_id"], []).append(u)
    for app in data.get("apps", []):
        app["urls"] = urls_by_app.get(app.get("id"), [])
    settings_map = {r["key"]: _safe_json(r.get("value")) for r in data.get("settings", [])}
    counts = await restore_all(session, {**data, "settings": settings_map})
    return counts


def _safe_json(raw):
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw
