"""Redis access — cache-aside, pub/sub to Notify, and the distributed
token-bucket rate limiter guarding the LLM budget.

`acquire_llm_permit` is the Phase 1 stub for the real mechanism discussed in
the design doc: a single bucket shared by every worker (not one per worker),
refilled to match the actual provider RPM, decremented atomically via a Lua
script so two workers racing for the last token can't both succeed.
"""

import redis.asyncio as redis

from jobpilot_shared.config import settings

_pool = redis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)


def get_client() -> redis.Redis:
    return redis.Redis(connection_pool=_pool)


async def ping() -> bool:
    client = get_client()
    return await client.ping()


# Atomic check-and-decrement: "is there a token AND take it" happens as one
# unit inside Redis. This is what prevents the "last token" race between two
# workers that a naive GET-then-decrement would allow.
_TOKEN_BUCKET_LUA = """
local current = tonumber(redis.call('GET', KEYS[1]) or ARGV[1])
if current > 0 then
  redis.call('DECR', KEYS[1])
  return 1
else
  return 0
end
"""


async def acquire_llm_permit(bucket_key: str = "llm:rate_limit:tokens") -> bool:
    """Returns True if a permit was acquired, False if the bucket is empty.

    Real implementation still needs a refill mechanism (e.g. a periodic job
    or lazy refill-on-read keyed by elapsed time) — this stub only shows the
    atomic acquire half, which is the part that actually prevents the race.
    """
    client = get_client()
    result = await client.eval(_TOKEN_BUCKET_LUA, 1, bucket_key, settings.llm_rate_limit_rpm)
    return bool(result)
