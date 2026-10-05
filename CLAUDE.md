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
| `frontend/` | Next.js | Dashboard UI: landing page, auth, Discover / Pipeline / Job Workspace / Profile. Dev-native (not containerized) — defaults to :3000, but whatever port it actually runs on must match `FRONTEND_URL` in `.env` (CORS + OAuth redirects depend on it) |
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

Phase 0, Phase 1, Phase 2, Phase 3, and Phase 4 are done. Phase 3 shipped
at a revised, smaller scope (see `docs/PHASE_3_PLAN.md`: GitHub ingestion
and all of chunking/embeddings/vector-store/retrieval deferred together,
since a single resume has no corpus large enough to need retrieval; what
shipped is just `POST /resumes` / `GET /resumes/active`). Phase 1 (auth,
Postgres schema, basic chat, cache-aside `/jobs`, rate limiter) is
re-verified against a live Postgres/Redis including the email+password/
Google rework. Phase 2 (LangGraph) built two separate graphs,
`graph.py` for `/chat` and `prepare_graph.py` for the "Prepare" pipeline
(resume-quality gate → Resume/Cover Letter sequential + Interview Prep's
curriculum generation in parallel → reviewer critique-and-revise → a real
human-in-the-loop `interrupt()` gate on the reviewer's proposal) — both
now live in `shared/jobpilot_shared/graph/` (moved there in Phase 4,
chunk 4, since `job-worker` needs them too and "same codebase, two deploy
targets" means shared logic doesn't live under `agent-core/app/` alone).
Interview Prep's actual conversation is a third, separately-checkpointed
graph (`graph/interview_graph.py`) — it's open-ended, so it can't join the
Prepare pipeline's fan-in the way a one-shot task can. Three places the
original roadmap wording didn't survive contact with the real design in
Phase 2 (no supervisor needed, what "parallel" actually means once
Interview Prep got richer, where human-in-the-loop actually belongs) —
full reasoning in `docs/PHASE_2_PLAN.md`.

Phase 4 (Job Worker) also scope-corrected its own roadmap wording — the
"Saga: reserve credit → resume → cover letter → compensate on failure"
didn't correspond to anything real (no credit system exists; BYOK/plans
are deferred to Phase 10 on purpose) and was replaced by making
`prepare_graph`'s own routing resumable on retry instead. What shipped:
Celery + RabbitMQ job ingestion (RemoteOK + Arbeitnow; Adzuna deferred —
needs credentials nobody's signed up for) with Celery Beat scheduling,
raw postings → MongoDB + normalized upserts → Postgres, a circuit breaker
+ retry/backoff/jitter around every external call, the `prepare_graph`
pipeline wrapped in one real Celery task (`run_prepare_pipeline`),
optimistic-locking `POST /applications/{id}/apply`, and a PDF
compile-and-inspect + ATS text-layer verification + relevance-weighted
cutting loop (`WeasyPrint` + `PyMuPDF`) wired into `prepare_graph` itself
as a real node. Full reasoning and verification notes for every chunk,
including a real cross-event-loop asyncpg bug found and fixed
(`dispose_engine()`), are in `docs/PHASE_4_PLAN.md`.

Phase 5 (Notify) is done. Scope-corrected the same way: of the roadmap's
three named push events ("new match," "tailoring ready," "interview
reminder"), only "tailoring ready" maps to anything real — the other two
need per-user job-matching and scheduled-interview features that don't
exist yet, so they're deferred rather than built as fake plumbing nothing
can ever fire. What shipped: real session-JWT auth on the WebSocket
upgrade (`notify/index.js` now verifies the same `jobpilot_session` cookie
agent-core does, rejecting with a real `401` before the handshake
completes); `jobpilot_shared.redis_client.publish_event()`, wired into
both places `Application.status` becomes `READY_TO_APPLY`; every event
logged to a MongoDB `notify_events` collection before the live push; and
the roadmap's "deliberately profile one blocking sync call" exercise, done
as a standalone script (`notify/blocking_demo.js`, kept fully separate
from the real message handler) that measured a synchronous call freezing
an unrelated connection's latency to 2003ms, then 6ms after moving the
same work to a `worker_threads` Worker. Full verification notes in
`docs/PHASE_5_PLAN.md`.

Phase 6 (Frontend) is done, designed fresh rather than from the old
"JobPilot Screens" mockup (explicit user choice). Three real backend gaps
were found and fixed before any screen was built: `GET /jobs` was still
Phase 1's hardcoded mock (never wired to Phase 4's real `JobPosting`
table), there was no `GET /applications` list endpoint for Pipeline, and
no CORS config existed for the frontend's origin at all. Stack: Next.js 15
(App Router, TypeScript) + Tailwind v4 + a shadcn/ui-style
`components/ui/` primitive library (Radix + `class-variance-authority`,
owned component code). Every color pairing was checked against the real
WCAG 2.1 contrast formula, not eyeballed — caught a real dark-mode
contrast failure (white text on the primary button, ~3:1) before it ever
reached a screen. Shipped: landing page, email/password + Google auth, an
auth-gated app shell, Discover (real per-resume keyword match scores),
Pipeline (the real four-column board), the Job Workspace (resume/cover-
letter/interview-prep tabs, pending-review accept/reject, mark-as-
applied), Profile (resume upload, GitHub connect), and live updates over
the real Notify WebSocket. A full real `/prepare` run through the actual
frontend's data contracts surfaced and fixed a second cross-event-loop
bug — the shared Redis connection pool (`jobpilot_shared/redis_client.py`,
new `dispose_pool()`), same root cause as Phase 4 chunk 4's Postgres bug.
Full verification notes in `docs/PHASE_6_PLAN.md`. Next up: **Phase 7** —
deploy to AWS for real.

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

**Frontend** (Phase 6, dev-native — not part of `docker compose`):

```bash
cd frontend && cp .env.example .env.local && npm install && npm run dev
```

Defaults to `http://localhost:3000`. If that port's already taken on your
machine, Next.js falls back to the next free one (3001, ...) and tells
you which — when that happens, update `.env`'s `FRONTEND_URL` to match
before testing login/CORS, or every cross-origin request will be silently
rejected (the backend only allows the one origin it's configured for).

## Where the rest of the design record lives

- `docs/DESIGN_DECISIONS.md` — the full why: UX flow, BYOK/plans model,
  scalability design (queues, distributed rate limiting, atomic Redis ops,
  multi-tenant fairness), service inventory.
- `docs/ROADMAP.md` — condensed phase-by-phase build plan (offline copy).
- The live interactive roadmap tracker and UI mockup are Claude artifacts —
  ask Bhavish for the links if you need the checkbox-tracked version or the
  clickable screen mockup.
