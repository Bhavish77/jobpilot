"""Circuit breaker — Phase 4, chunk 3.

Redis-backed, not in-process, for the same reason the LLM rate limiter is:
job-worker forks into multiple sub-processes (concurrency=12, prefork) and
could run as multiple container replicas — a circuit that only lived in one
process's memory would be blind to failures happening in every other
process hitting the same external API.

Deliberately *not* using the rate limiter's atomic Lua-script pattern here.
That mattered there because many concurrent requests could race for the
last token at once. Here, failures accumulate one HTTP call at a time
during an occasional ingestion run — far lower concurrency, far lower
stakes if two near-simultaneous failures under-count by one. Match the
mechanism's rigor to the actual risk, not every Redis primitive needs the
same atomicity guarantee.

Shape: track consecutive failures per source. After `failure_threshold` in
a row, "open" the circuit — stop even attempting calls for
`cooldown_seconds`, failing fast instead of wasting a request (and its full
timeout) on something very likely to fail again. Once the cooldown expires,
the next call is let through as a trial; success resets the failure count,
another failure re-opens the circuit for a fresh cooldown.
"""

import time
from typing import Awaitable, Callable, TypeVar

from jobpilot_shared.redis_client import get_client

T = TypeVar("T")


class CircuitOpenError(Exception):
    """Raised instead of even attempting a call, while the circuit is open."""


async def call_with_circuit_breaker(
    source: str,
    fn: Callable[[], Awaitable[T]],
    *,
    failure_threshold: int = 3,
    cooldown_seconds: int = 300,
) -> T:
    client = get_client()
    opened_key = f"circuit:{source}:opened_until"
    failures_key = f"circuit:{source}:failures"

    opened_until = await client.get(opened_key)
    if opened_until and float(opened_until) > time.time():
        raise CircuitOpenError(
            f"Circuit open for {source!r} — {failure_threshold}+ recent failures, cooling down."
        )

    try:
        result = await fn()
    except Exception:
        failures = await client.incr(failures_key)
        if failures >= failure_threshold:
            await client.set(opened_key, time.time() + cooldown_seconds)
            await client.set(failures_key, 0)  # fresh count once it reopens after cooldown
        raise
    else:
        await client.set(failures_key, 0)
        return result
