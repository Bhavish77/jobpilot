# JobPilot — context for Claude Code

Read this first when picking up work in this repo. Fuller background lives in
`docs/DESIGN_DECISIONS.md` (the why) and `docs/ROADMAP.md` (the phase-by-phase
build plan) — read those too before making architectural changes.

## What this is

An AI job-search and application-prep assistant, built as one mega-project to
cover frontend + backend + AI + systems design in a single real, polyglot
system. No fixed timeline — depth over speed, one phase at a time, no day
counts. **It never auto-submits applications.** It prepares tailored resumes,
cover letters, and interview prep; the human reviews and applies themselves.
This is a permanent product decision, not a v1 limitation — don't add
auto-submit later without the user explicitly re-opening that decision.

## Services

| Path | Language | Role |
|---|---|---|
| `agent-core/` | Python (FastAPI) | Auth, LangGraph supervisor + specialist agents, RAG, the API the frontend talks to |
| `job-worker/` | Python (Celery) | Job-search ingestion + the prepare-application pipeline, wrapped in circuit breakers/retries/timeouts |
| `notify/` | Node.js | Per-user WebSocket connections, subscribes to Redis pub/sub, pushes live updates |
| `frontend/` | Next.js | Not built yet (Phase 6) — dashboard UI: Profile / Discover / Pipeline / Job Workspace |
| `shared/` | Python package (`jobpilot_shared`) | Config, DB/Mongo/Redis clients, models, Celery app + tasks, auth — imported by both `agent-core` and `job-worker` so they're one codebase on two deployment targets |

Managed infra (docker-compose): Postgres, MongoDB, Redis, RabbitMQ. Vector
store (Chroma) and S3 arrive in Phase 3/7.

## Standing design rules — don't relitigate these without asking

- **Discover vs. Pipeline**: Discover only browses/selects/triggers "Prepare".
  It never shows resume/cover-letter/interview-prep content directly. Pipeline
  only holds jobs that have started the pipeline (columns: Preparing → Ready
  to apply → Applied → Interviewing). Clicking a Pipeline card opens the Job
  Workspace (the only place with the 3 tabs). This was a deliberate UX fix —
  see DESIGN_DECISIONS.md — don't collapse the two screens back together.
- **Prepare-only, no auto-submit.** See above.
- **Auth is provider-agnostic; GitHub is optional, not login.** Sign-in is
  email+password or Google OAuth — either works for any job seeker, not just
  developers. GitHub is a separate, optional connection made later
  (`/auth/github/connect`, from the profile screen) purely to grant Phase 3's
  RAG ingestion read access to the user's repos. It is never required to use
  JobPilot. (Supersedes the original "GitHub OAuth does double duty" design —
  see `docs/DESIGN_DECISIONS.md`, "Auth model," for why it changed.)
- **Same codebase, two deploy targets**: put shared logic in `shared/`, not
  duplicated between `agent-core` and `job-worker`.
- **Rate limiting is a shared Redis token bucket**, not per-worker, sized to
  the real LLM provider RPM. Every LLM call goes through
  `jobpilot_shared.redis_client.acquire_llm_permit()` first. This is proven
  atomic under concurrency (tested: 20 concurrent acquires against a 5-token
  bucket granted exactly 5) — don't replace the Lua `EVAL` check-and-decrement
  with a naive GET-then-write, that reintroduces the exact race it fixes.
- **Migrations run sync, the app runs async.** Alembic uses the `psycopg`
  (sync) driver against `settings.sync_database_url`; the app uses `asyncpg`
  via `settings.database_url`. Don't try to make Alembic use the async engine.
- **BYOK/plans/multi-tenant fairness are deferred to Phase 10 on purpose.**
  Don't add key_mode branching or plan-gated quotas earlier than that unless
  asked — v1 is a single managed key, no plans.

## Current status

Phase 0 (scaffold) and Phase 1 (Agent Core v1: email+password + Google auth
with GitHub as an optional connect-later flow, Postgres schema, basic
LangChain chat, cache-aside `/jobs`, the rate limiter) are done. The DB layer
was verified against a real local Postgres + Redis in the original
GitHub-only version; the auth rework (email+password/Google primary, GitHub
optional) hasn't been re-run against a live DB yet — do that before calling
it verified again. Next up: **Phase 2** — rebuild the chatbot as a LangGraph
`StateGraph`, add the supervisor + Resume / Cover Letter / Interview Prep
specialist agents (Cover Letter sequential after Resume, Interview Prep
parallel), and cross-session checkpointing in Postgres.

## Running it locally

```bash
cp .env.example .env
docker compose up -d postgres mongo redis rabbitmq
cd shared && pip install -e . && alembic upgrade head && cd ..
docker compose up -d --build
curl localhost:8000/health
curl localhost:8000/ready
```

Email+password login (`POST /auth/register`, `POST /auth/login`) works
against the local Postgres with no external setup. To exercise Google login
for real, create a Google OAuth client with redirect URI
`http://localhost:8000/auth/google/callback` and put its client id/secret in
`.env`. GitHub is optional and only needed once Phase 3's RAG ingestion is
being tested — create a GitHub OAuth App with callback
`http://localhost:8000/auth/github/callback` when you get there.

## Where the rest of the design record lives

- `docs/DESIGN_DECISIONS.md` — the full why: UX flow, BYOK/plans model,
  scalability design (queues, distributed rate limiting, atomic Redis ops,
  multi-tenant fairness), service inventory.
- `docs/ROADMAP.md` — condensed phase-by-phase build plan (offline copy).
- The live interactive roadmap tracker and UI mockup are Claude artifacts —
  ask Bhavish for the links if you need the checkbox-tracked version or the
  clickable screen mockup.
