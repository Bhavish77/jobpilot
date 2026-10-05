"""Redis access — cache-aside, pub/sub to Notify, and the distributed
rate limiting guarding the LLM budget.

Two genuinely separate gates, found the hard way to actually be separate
(see docs/PHASE_6_PLAN.md's rate-limiter writeup) — a finished RPM bucket
alone was never going to stop the real failure that triggered this:

- `acquire_llm_permit`: requests-per-minute, a single bucket shared by
  every worker (not one per worker), refilled lazily based on real
  elapsed time, decremented atomically via a Lua script so two workers
  racing for the last token can't both succeed. Protects against *burst*
  traffic and our own infra.
- `acquire_daily_quota`: requests-per-day, a completely different axis —
  free-tier providers cap total daily calls independent of how fast
  you're allowed to make them. Without this, nothing locally ever knew
  the daily budget existed until the provider's own 429 said so, often
  mid-pipeline after other steps had already succeeded.
"""

import json
from datetime import datetime, timezone

import redis.asyncio as redis

from jobpilot_shared.config import settings

# Must match notify/index.js's EVENTS_CHANNEL exactly — the one channel
# every Notify instance subscribes to (see docs/PHASE_5_PLAN.md).
EVENTS_CHANNEL = "jobpilot:events"

_pool = redis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)


def get_client() -> redis.Redis:
    return redis.Redis(connection_pool=_pool)


async def ping() -> bool:
    client = get_client()
    return await client.ping()


async def dispose_pool() -> None:
    """Same bug, same fix as db.py's dispose_engine() (Phase 4, chunk 4):
    `_pool` is created once at import time and binds to whichever event
    loop first uses it. Safe for agent-core (one persistent event loop),
    not for Celery tasks — each task's own asyncio.run() call gets a
    fresh loop, and a connection left in the pool from a previous task's
    now-closed loop breaks on reuse ("Event loop is closed" during
    disconnect — found for real running generate_curriculum back-to-back
    with other tasks in the same long-lived job-worker process). Call at
    the end of any asyncio.run()-wrapped Celery task that touched Redis
    (acquire_llm_permit, publish_event) — which, via call_llm's rate
    limiter, is every prepare_tasks.py run."""
    await _pool.disconnect()


# Lazy refill, computed from elapsed wall-clock time, entirely inside the
# Lua script — everything in one atomic EVAL so two workers racing for the
# last token still can't both succeed, same guarantee the Phase 1 stub had,
# now with the refill half that stub's own docstring said was still needed.
# Uses Redis's own TIME command rather than a client-supplied timestamp —
# multiple callers (agent-core, 12 job-worker processes) would otherwise
# each bring a slightly different clock to the same shared bucket.
_TOKEN_BUCKET_LUA = """
local tokens = tonumber(redis.call('HGET', KEYS[1], 'tokens'))
local last_refill = tonumber(redis.call('HGET', KEYS[1], 'last_refill'))
local capacity = tonumber(ARGV[1])
local refill_per_second = tonumber(ARGV[2])

local time_result = redis.call('TIME')
local now = tonumber(time_result[1]) + (tonumber(time_result[2]) / 1000000)

if tokens == nil then
  tokens = capacity
  last_refill = now
end

local elapsed = now - last_refill
if elapsed > 0 then
  tokens = math.min(capacity, tokens + (elapsed * refill_per_second))
  last_refill = now
end

local granted = 0
if tokens >= 1 then
  tokens = tokens - 1
  granted = 1
end

redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'last_refill', tostring(last_refill))
-- Safety TTL so an abandoned bucket key doesn't live forever — refreshed
-- on every call, so it only ever expires if nothing touches it for a
-- while (meaning there's nothing to protect against anyway).
redis.call('EXPIRE', KEYS[1], 120)

return granted
"""


async def acquire_llm_permit(bucket_key: str = "llm:rate_limit:tokens") -> bool:
    """Returns True if a permit was acquired, False if the bucket is
    currently empty (will refill as real time passes — see the Lua
    script above). Protects against burst RPM only; see
    acquire_daily_quota for the separate, much stricter per-day cap a
    free-tier provider actually enforces."""
    client = get_client()
    refill_per_second = settings.llm_rate_limit_rpm / 60
    result = await client.eval(_TOKEN_BUCKET_LUA, 1, bucket_key, settings.llm_rate_limit_rpm, refill_per_second)
    return bool(result)


async def acquire_daily_quota(quota_key: str = "llm:daily_quota") -> bool:
    """A provider's free tier typically caps total calls per *day*,
    entirely independent of RPM — Gemini's own 429 named this exact
    constraint ("GenerateRequestsPerDayPerProjectPerModel-FreeTier").
    Scoped to today's UTC date so it resets daily without needing a
    cleanup job; `INCR` is itself atomic (no Lua needed, nothing to race
    — "add one and read the new total" is one indivisible Redis command).
    This is a best-effort local mirror of the provider's real quota, not
    an authoritative one — we don't know their exact reset window (the
    real error reported an odd offset like "11h42m," not a clean
    midnight-UTC reset), so this can't guarantee perfect alignment, only
    a much closer approximation than having no local tracking at all."""
    client = get_client()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"{quota_key}:{today}"
    count = await client.incr(key)
    if count == 1:
        await client.expire(key, 60 * 60 * 25)  # a bit over 24h, self-healing against clock drift
    return count <= settings.llm_daily_quota


async def publish_event(user_id: str, event_type: str, payload: dict) -> None:
    """Fire-and-forget: PUBLISH has no persistence or delivery guarantee —
    if no Notify instance is subscribed right now, the message is just
    gone. That's fine for a live "push" nice-to-have; Phase 5 chunk 3's
    Mongo log on the Notify side is what gives this a durable record,
    not this call. Shape must match what notify/index.js's subscriber
    expects: {userId, type, payload}."""
    client = get_client()
    event = {"userId": user_id, "type": event_type, "payload": payload}
    await client.publish(EVENTS_CHANNEL, json.dumps(event))
