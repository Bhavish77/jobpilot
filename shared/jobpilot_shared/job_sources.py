"""Job board ingestion — Phase 4.

Two public, free, no-auth APIs: RemoteOK and Arbeitnow. Adzuna needs API
credentials (app_id + app_key) nobody's signed up for yet — deferred the
same way GitHub ingestion was deferred in Phase 3, not forgotten.

fetch_* functions return each source's response completely untouched —
matches the design-doc decision to store raw postings in Mongo exactly as
received. normalize_* functions do the actual cleanup, only on the way
into Postgres. Keeping these as separate, pure functions (no I/O inside
normalize_*) is what makes them testable with hand-built fake data instead
of hitting the real APIs on every test run.

Chunk 3: every fetch now has an explicit timeout, retries transient
failures with exponential backoff + jitter (tenacity — real third-party
HTTP calls are exactly the flaky-external-dependency case these patterns
exist for, unlike past phases' false starts), and only retries errors a
retry could plausibly fix (connection/timeout issues, 5xx) — never 4xx,
since retrying a malformed request just produces the same 4xx again. The
circuit breaker wraps *outside* the retried call, at a coarser grain: if a
source keeps failing across multiple separate calls (not just within one
retry burst), stop even attempting it for a cooldown instead of burning a
full timeout on every ingestion run.
"""

import re
from datetime import datetime, timezone

import httpx
import tenacity
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from jobpilot_shared.circuit_breaker import call_with_circuit_breaker
from jobpilot_shared.models import JobPosting
from jobpilot_shared.mongo import get_db

REMOTEOK_URL = "https://remoteok.com/api"
ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"

_FETCH_TIMEOUT_SECONDS = 10.0

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    no_tags = _HTML_TAG_RE.sub(" ", text or "")
    return _WHITESPACE_RE.sub(" ", no_tags).strip()


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True  # connection refused, DNS failure, timeout, etc.
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500  # retry server errors, never 4xx
    return False


_retry_policy = tenacity.retry(
    stop=tenacity.stop_after_attempt(3),
    wait=tenacity.wait_random_exponential(multiplier=1, max=10),  # backoff + jitter in one call
    retry=tenacity.retry_if_exception(_is_retryable),
    reraise=True,
)


@_retry_policy
async def _fetch_remoteok_raw() -> list[dict]:
    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SECONDS) as client:
        resp = await client.get(REMOTEOK_URL, headers={"User-Agent": "JobPilot/0.1"})
        resp.raise_for_status()
        return resp.json()


@_retry_policy
async def _fetch_arbeitnow_raw() -> list[dict]:
    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SECONDS) as client:
        resp = await client.get(ARBEITNOW_URL)
        resp.raise_for_status()
        return resp.json()["data"]


async def fetch_remoteok() -> list[dict]:
    data = await call_with_circuit_breaker("remoteok", _fetch_remoteok_raw)
    # The first array element is RemoteOK's own legal/notice object, not a
    # job posting — it has no "id" field, which every real posting has.
    return [job for job in data if "id" in job]


async def fetch_arbeitnow() -> list[dict]:
    return await call_with_circuit_breaker("arbeitnow", _fetch_arbeitnow_raw)


def normalize_remoteok(raw: dict) -> dict:
    return {
        "source": "remoteok",
        "external_id": str(raw["id"]),
        "title": raw.get("position", ""),
        "company": raw.get("company", ""),
        "location": raw.get("location") or None,
        "is_remote": True,  # RemoteOK is remote-only by definition
        "url": raw.get("url") or raw.get("apply_url", ""),
        "description": _strip_html(raw.get("description", "")),
        "tags": raw.get("tags", []) or [],
        "salary_min": raw.get("salary_min"),
        "salary_max": raw.get("salary_max"),
        "posted_at": datetime.fromtimestamp(raw["epoch"], tz=timezone.utc) if raw.get("epoch") else None,
    }


def normalize_arbeitnow(raw: dict) -> dict:
    return {
        "source": "arbeitnow",
        "external_id": raw["slug"],
        "title": raw.get("title", ""),
        "company": raw.get("company_name", ""),
        "location": raw.get("location") or None,
        "is_remote": bool(raw.get("remote", False)),
        "url": raw.get("url", ""),
        "description": _strip_html(raw.get("description", "")),
        "tags": raw.get("tags", []) or [],
        "salary_min": None,
        "salary_max": None,
        "posted_at": datetime.fromtimestamp(raw["created_at"], tz=timezone.utc) if raw.get("created_at") else None,
    }


async def store_raw_postings(source: str, raw_postings: list[dict]) -> None:
    """Append-only, by design — Mongo is the historical/unprocessed log,
    not deduplicated. Postgres (upsert_job_postings) is the deduplicated
    current-state store."""
    if not raw_postings:
        return
    db = get_db()
    tagged = [
        {**posting, "_source": source, "_ingested_at": datetime.now(timezone.utc)} for posting in raw_postings
    ]
    await db["raw_job_postings"].insert_many(tagged)


async def upsert_job_postings(session: AsyncSession, normalized: list[dict]) -> int:
    """Insert new postings, update existing ones matched by (source,
    external_id) — a daily re-run shouldn't create duplicate rows for
    listings that are still live."""
    if not normalized:
        return 0
    stmt = pg_insert(JobPosting).values(normalized)
    update_cols = {col: stmt.excluded[col] for col in normalized[0] if col not in ("source", "external_id")}
    stmt = stmt.on_conflict_do_update(index_elements=["source", "external_id"], set_=update_cols)
    await session.execute(stmt)
    await session.commit()
    return len(normalized)
