"""GET /jobs — the real cache-aside pattern (design doc, "Caching &
messaging" topic), wired up now even though the data behind it is a mock
until Phase 4 builds real ingestion.

Cache-aside: check Redis first: on a hit, return it, done. On a miss,
compute the value (here: fake it — Phase 4 replaces this with a real query
against the scored/normalized Postgres job table), write it to Redis with a
TTL, then return it. Every request after the first within the TTL window
never touches the "real" source at all.
"""

import json

from fastapi import APIRouter, Depends

from jobpilot_shared.models import User
from jobpilot_shared.redis_client import get_client

from app.deps import get_current_user

router = APIRouter(prefix="/jobs", tags=["jobs"])

CACHE_KEY = "jobs:listing:v1"
CACHE_TTL_SECONDS = 300

# Stand-in for Phase 4's real pipeline (Adzuna/RemoteOK/Arbeitnow ingestion
# -> Mongo raw -> scored/normalized Postgres). The shape here is what the
# Discover screen in the UI mockup actually renders against.
_MOCK_JOBS = [
    {"id": "anthropic-ai-eng", "title": "AI Engineer", "company": "Anthropic", "match_score": 0.94},
    {"id": "scaleai-ml-eng", "title": "ML Engineer", "company": "Scale AI", "match_score": 0.81},
    {"id": "vercel-fullstack", "title": "Full-stack Engineer", "company": "Vercel", "match_score": 0.77},
]


async def _load_jobs_from_source() -> list[dict]:
    """Stands in for the Phase 4 query against normalized Postgres job rows."""
    return _MOCK_JOBS


@router.get("")
async def list_jobs(user: User = Depends(get_current_user)) -> dict:
    redis_client = get_client()

    cached = await redis_client.get(CACHE_KEY)
    if cached is not None:
        return {"source": "cache", "jobs": json.loads(cached)}

    jobs = await _load_jobs_from_source()
    await redis_client.set(CACHE_KEY, json.dumps(jobs), ex=CACHE_TTL_SECONDS)
    return {"source": "origin", "jobs": jobs}
