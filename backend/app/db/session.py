"""数据库会话：SQLite 运行主库（aiosqlite）。

连接层基于 SQLAlchemy，保持可对接 MySQL（镜像推送见 dev-plan P23）。
"""

import json
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    f"sqlite+aiosqlite:///{Path(settings.data_dir) / 'portal.db'}",
    echo=False,
    # 中文等非 ASCII 字符原样入库（否则 LIKE 检索/导出可读性受影响）
    json_serializer=lambda obj: json.dumps(obj, ensure_ascii=False),
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：请求级会话。"""
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    """建表并写入默认设置（P0.3）。"""
    from app.models import DEFAULT_SETTINGS, Base, Setting  # 局部导入确保模型注册

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 轻量迁移：create_all 不会给已有表补列，逐条尝试（列/表已存在则忽略）
        for stmt in (
            "ALTER TABLE categories ADD COLUMN icon_type VARCHAR(16)",
            # P5.5：monitor_samples 补每核使用率列（历史每核曲线）
            "ALTER TABLE monitor_samples ADD COLUMN cpu_cores TEXT",
            # P5 增强：GPU 采集列（io 列建表即有）
            "ALTER TABLE monitor_samples ADD COLUMN gpu TEXT",
            # P7.4/P7.5：用户备注、应用可见性授权用户
            "ALTER TABLE users ADD COLUMN remark TEXT DEFAULT ''",
            "ALTER TABLE apps ADD COLUMN visible_users TEXT DEFAULT '[]'",
        ):
            try:
                await conn.exec_driver_sql(stmt)
            except Exception:
                pass
        # 图标库 v2：历史 custom_icons 表数据迁入 icons（source='custom'）
        try:
            rows = (await conn.exec_driver_sql("SELECT name, path FROM custom_icons")).fetchall()
            for name, path in rows:
                await conn.exec_driver_sql(
                    "INSERT OR IGNORE INTO icons"
                    " (name, source, path, hidden, created_at, updated_at)"
                    " VALUES (?, 'custom', ?, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                    (name, path),
                )
        except Exception:
            pass  # 旧表不存在（全新库）
    async with SessionLocal() as session:
        # 默认设置只补缺（INSERT if missing）：不能用 merge——
        # merge 会在每次启动时把用户已修改的设置重置回默认值
        for key, value in DEFAULT_SETTINGS.items():
            if await session.get(Setting, key) is None:
                session.add(Setting(key=key, value=value))
        await session.commit()
