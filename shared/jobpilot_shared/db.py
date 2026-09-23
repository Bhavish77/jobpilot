"""Postgres access — async SQLAlchemy engine, shared by both services.

Phase 1 fills in real models (users, resumes, applications). For now this is
just the engine/session factory so agent-core's /ready check and job-worker's
task bodies both have one place to get a connection from.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jobpilot_shared.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        yield session


async def ping() -> bool:
    """Used by /ready — cheap connectivity check, not a real query yet."""
    async with engine.connect() as conn:
        await conn.exec_driver_sql("SELECT 1")
    return True
