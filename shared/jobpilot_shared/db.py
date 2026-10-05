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


async def dispose_engine() -> None:
    """Call at the end of any asyncio.run()-wrapped Celery task that used
    this engine/async_session (Phase 4, chunk 4 — found by a real crash,
    not anticipated in advance). `engine` is created once at import time;
    its connection pool binds to whichever event loop first uses it. Safe
    for agent-core (uvicorn runs one event loop for the app's entire
    life), but not for Celery tasks — each `asyncio.run()` call spins up
    and tears down its own separate loop, so a connection left in the pool
    from one task's loop breaks the next task that reuses it ("Task ...
    got Future ... attached to a different loop"). Disposing the pool
    before this loop closes forces the next task's new loop to open fresh
    connections instead."""
    await engine.dispose()
