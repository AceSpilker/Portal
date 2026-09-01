"""数据库会话：SQLite 运行主库（aiosqlite）。

连接层基于 SQLAlchemy，保持可对接 MySQL（镜像推送见 dev-plan P23）。
"""
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    f"sqlite+aiosqlite:///{Path(settings.data_dir) / 'portal.db'}",
    echo=False,
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
    async with SessionLocal() as session:
        for key, value in DEFAULT_SETTINGS.items():
            await session.merge(Setting(key=key, value=value))
        await session.commit()
