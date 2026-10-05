"""Job ingestion Celery task — Phase 4.

Separate from tasks.py on purpose: tasks.py is the prepare-application
pipeline (resume/cover-letter/interview-prep, LLM-based); this is job-board
ingestion, a completely different pipeline with nothing in common except
both being Celery tasks.

dispose_engine()/dispose_pool() at the end of the task are required, not
optional — see db.py's and redis_client.py's docstrings for why (real
crashes found this: "attached to a different loop" for Postgres,
"Event loop is closed" for Redis, both once a task had run more than once
in the same long-lived worker process). This task's circuit breaker
(job_sources.py's fetchers) touches the shared Redis pool too, so both
disposals apply here, not just the Postgres one.
"""

import asyncio

from jobpilot_shared.celery_app import celery_app
from jobpilot_shared.db import async_session, dispose_engine
from jobpilot_shared.job_sources import (
    fetch_arbeitnow,
    fetch_remoteok,
    normalize_arbeitnow,
    normalize_remoteok,
    store_raw_postings,
    upsert_job_postings,
)
from jobpilot_shared.redis_client import dispose_pool as dispose_redis_pool

_SOURCES = {
    "remoteok": (fetch_remoteok, normalize_remoteok),
    "arbeitnow": (fetch_arbeitnow, normalize_arbeitnow),
}


async def _ingest_source(source: str) -> dict:
    fetch_fn, normalize_fn = _SOURCES[source]
    raw_postings = await fetch_fn()
    await store_raw_postings(source, raw_postings)

    normalized = [normalize_fn(raw) for raw in raw_postings]
    async with async_session() as session:
        count = await upsert_job_postings(session, normalized)

    return {"source": source, "raw_count": len(raw_postings), "upserted_count": count}


async def _ingest_all_sources() -> list[dict]:
    return [await _ingest_source(source) for source in _SOURCES]


async def _ingest_all_sources_and_dispose() -> list[dict]:
    try:
        return await _ingest_all_sources()
    finally:
        await dispose_engine()
        await dispose_redis_pool()


@celery_app.task(name="jobpilot.ingest_jobs")
def ingest_jobs() -> list[dict]:
    """Scheduled daily via Celery Beat (see celery_app.py). Runs each
    source sequentially, not in parallel — these are polite, free public
    APIs; no reason to hit them concurrently and risk looking abusive."""
    return asyncio.run(_ingest_all_sources_and_dispose())
