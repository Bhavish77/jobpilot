# Sync vs async DB drivers (psycopg vs asyncpg)

Where this shows up in JobPilot: [shared/jobpilot_shared/config.py](../../shared/jobpilot_shared/config.py)
defines `database_url` (used by the app, `postgresql+asyncpg://...`) and a
computed `sync_database_url` property (used by Alembic migrations,
`postgresql+psycopg://...`) — same database, different driver.

## The core idea

A **driver** is the translator between your code and the database: it opens
the connection, sends SQL, turns the response into objects your language
understands. `psycopg` and `asyncpg` are two different translators for the
same Postgres. The difference is *how they wait for a reply*.

- **Sync (`psycopg`)** — your program sends a query and **blocks**: it stops
  and does nothing else until Postgres replies. Like calling someone and
  standing silently by the phone until they pick up.
- **Async (`asyncpg`)**, used with Python's `async`/`await` — your program
  sends a query and says "wake me up when this replies; meanwhile, go do
  something else." Like texting several people and doing other things while
  you wait for replies, instead of waiting on hold one call at a time.

## Why a web server cares

A web server handles many users' requests around the same time. A database
query takes real time — network round-trip + Postgres doing the work. If the
server uses a **blocking/sync** driver, while User A's query is in flight the
*entire process* is frozen — User B's request can't even begin. With an
**async** driver, the waiting time is handed back to the event loop, which
can work on User B while User A's query is still out — then resumes User A
when the reply lands. One process, many requests in flight at once. That's
the whole reason `agent-core` (FastAPI) uses `asyncpg`.

This only helps because the wait is *I/O-bound* (network/disk, not CPU). If
the work were CPU-heavy (e.g. crunching numbers), async wouldn't help — the
process would still be busy, just not on I/O.

## Why Alembic (migrations) uses sync instead

Alembic isn't a server juggling concurrent requests. It's a command you run
once from a terminal — create/alter some tables, then exit. There's nothing
to juggle; it's inherently one task, start to finish. On top of that,
Alembic's internals (especially "autogenerate," which diffs your Python
models against the live DB schema) were built around plain synchronous
SQLAlchemy and don't natively understand `async`/`await`. Using the async
driver here would mean wrapping every migration step in an event loop, for a
tool that never needed concurrency in the first place — complexity with no
payoff.

## The reassuring part

It's the *exact same Postgres database* — same host, same credentials, same
data. Only the driver differs. In a SQLAlchemy connection string, the part
before `://` (`postgresql+asyncpg` vs `postgresql+psycopg`) tells SQLAlchemy
which dialect+driver combo to use. `sync_database_url` just swaps that one
piece and leaves the host/user/password/db name untouched:

```python
@property
def sync_database_url(self) -> str:
    return self.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
```

## Rule of thumb

- Long-running server handling concurrent requests, I/O-bound work → async
  driver.
- One-shot script/CLI tool, or a library that doesn't support async → sync
  driver.
- Don't force async everywhere "for performance" — it only pays off when
  something else can usefully run during the wait. A one-shot migration has
  nothing else to run.
