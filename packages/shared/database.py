"""Asynchronous database engine and session management.
Supports production PostgreSQL (asyncpg) and development/testing SQLite (aiosqlite).
"""

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from packages.shared.config import settings
from packages.shared.models import Base

# Engine configuration
engine_kwargs = {"echo": settings.DEBUG, "future": True}

if settings.DATABASE_URL.startswith("postgresql+asyncpg"):
    engine_kwargs.update({
        "pool_size": settings.DATABASE_POOL_SIZE,
        "max_overflow": settings.DATABASE_MAX_OVERFLOW,
        "pool_pre_ping": True,
    })

engine: AsyncEngine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI route handlers and workers to obtain an isolated DB session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Initialize all database tables defined in SQLAlchemy models."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if "sqlite" in settings.DATABASE_URL:
            from sqlalchemy import text
            try:
                res = await conn.execute(text("PRAGMA table_info(requirements);"))
                columns = [row[1] for row in res.fetchall()]
                if columns and "certainty" not in columns:
                    await conn.execute(text("ALTER TABLE requirements ADD COLUMN certainty VARCHAR(32) DEFAULT 'CLIENT_STATED' NOT NULL;"))
            except Exception:
                pass


async def close_db() -> None:
    """Safely dispose of database connection pools."""
    await engine.dispose()
