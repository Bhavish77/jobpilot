# JobPilot

An AI job-search and application-prep assistant — resume tailoring, cover
letters, and interview prep, grounded in your real background. Built as a
single polyglot system (Python, Node.js, Next.js) covering backend
engineering, AI agent orchestration, and frontend in one real product, not
three toy demos.

**JobPilot never auto-submits applications.** It prepares a tailored
resume, cover letter, and interview prep for a job you pick; you review
everything and apply yourself. This is a permanent product decision, not a
v1 limitation.

## How it works

1. You upload a resume (paste text or a PDF — text is extracted server-side).
2. **Discover** shows real ingested job postings, ranked by keyword overlap
   against your resume.
3. Hit **Prepare** on one or more jobs. A LangGraph pipeline drafts a
   tailored resume and cover letter, runs a critique-and-revise pass, builds
   an interview-prep curriculum from the real gaps between your background
   and the job, and compiles/verifies the resume the way an ATS parser
   would (real PDF text-layer check, automatic relevance-weighted cutting
   if it overflows one page).
4. You review the proposed changes (a real human-in-the-loop approval step)
   in the **Job Workspace**, chat with the Interview Prep agent, and mark
   the job **Applied** once you've actually applied — yourself, on the real
   job board.
5. **Pipeline** tracks every job you've started, from Preparing through
   Applied.

## Architecture

```
                         ┌─────────────┐
   Browser  ───────────▶ │  frontend   │  Next.js, :3000 (dev-native)
                         └──────┬──────┘
                                │ REST (cookie auth) + WebSocket
                 ┌──────────────┼───────────────────┐
                 ▼                                   ▼
         ┌───────────────┐                   ┌───────────────┐
         │  agent-core   │                   │    notify     │
         │ FastAPI :8000 │                   │ Node.js :4000 │
         └───────┬───────┘                   └───────┬───────┘
                 │ enqueues                          │ subscribes
                 ▼                                    │
         ┌───────────────┐   Redis pub/sub ───────────┘
         │  job-worker    │  (events: tailoring_ready, ...)
         │ Celery + Beat  │
         └───────┬────────┘
                 │
     ┌───────────┼─────────────┬─────────────┬──────────────┐
     ▼           ▼              ▼             ▼              ▼
 Postgres      MongoDB        Redis       RabbitMQ      Gemini API
 (relational   (raw job       (cache +    (Celery       (LLM calls,
  data +       postings,      rate        broker)        gated by a
  LangGraph    notify event   limiter +                  shared Redis
  checkpoints) log)           pub/sub)                    rate limiter)
```

`agent-core` and `job-worker` both import a shared Python package
(`shared/jobpilot_shared`) — one codebase, two deployment targets, so
business logic (the LangGraph pipeline, models, rate limiter, PDF/ATS
verification) is never duplicated between the request-serving API and the
background worker that actually runs it.

### Services

| Path | Language | Role |
|---|---|---|
| `agent-core/` | Python (FastAPI) | Auth (email+password + Google OAuth, GitHub optional), the LangGraph `/prepare` and `/interview` pipelines, `/jobs`, `/applications` — the API the frontend talks to |
| `job-worker/` | Python (Celery) | Runs the Prepare pipeline (resume → cover letter → review → interview-prep curriculum → ATS verification) off the request path, plus daily job-board ingestion (Celery Beat) |
| `notify/` | Node.js | Per-user WebSocket connections; subscribes to Redis pub/sub and pushes live updates (e.g. "your tailored resume is ready") |
| `frontend/` | Next.js (App Router, TypeScript, Tailwind v4) | The dashboard UI — landing page, auth, Discover, Pipeline, Job Workspace, Profile |
| `shared/` | Python package (`jobpilot_shared`) | Config, DB/Mongo/Redis clients, SQLAlchemy models, the LangGraph pipeline itself, Celery app + tasks, auth — imported by both `agent-core` and `job-worker` |

Managed infrastructure (docker-compose): **Postgres** (relational data +
LangGraph's own checkpoint tables), **MongoDB** (raw ingested job postings,
Notify's event log), **Redis** (cache-aside, the distributed LLM rate
limiter, pub/sub to Notify), **RabbitMQ** (Celery's broker).

## A few things worth knowing before reading the code

- **Resumable pipeline, not fire-and-forget.** The Prepare pipeline is a
  single LangGraph `StateGraph`, checkpointed in Postgres after every step.
  If a task fails (a transient provider error, a crash), retrying re-enters
  at exactly the step that failed — never redoes finished LLM calls.
- **Two real rate-limit gates, not one.** A Redis token bucket for
  requests-per-minute (atomic, lazily refilled based on real elapsed time)
  *and* a separate daily-quota counter — a provider's free tier caps total
  calls per day independent of how fast you're allowed to make them, which
  turned out to be the constraint that actually mattered in practice.
- **Prepare-only is enforced in the UX, not just stated.** There is no
  code path anywhere that submits anything to an external job board.
- **The ATS verification loop is real**, not cosmetic: the generated resume
  is compiled to an actual PDF (WeasyPrint), its text layer is extracted
  the way an ATS parser would (PyMuPDF) to confirm contact info and
  keywords actually survive as real text, and if it overflows one page, the
  lowest-relevance bullet is cut and it recompiles — automatically.
- **Every non-obvious decision is written down.** `docs/DESIGN_DECISIONS.md`
  is the living "why" behind the architecture; `docs/PHASE_*_PLAN.md` files
  are a complete build log per phase, including real bugs found during
  testing and how they were actually fixed (not just what shipped).

## Project status

All of Phases 0–6 are built and verified against the real running stack:
scaffold → auth/chat/cache → LangGraph multi-agent pipeline → resume RAG →
job ingestion/resilience/PDF pipeline → Notify → the full frontend. See
`docs/ROADMAP.md` for the phase-by-phase log and `docs/PHASE_6_PLAN.md`
for the most recent (frontend + a round of real production bug fixes).

Next up: **Phase 7** — deploying this for real.

## Running it locally

**Prerequisites:** Docker Desktop, Node.js 20+, a Gemini API key (free tier
works — [aistudio.google.com](https://aistudio.google.com)).

```bash
cp .env.example .env
# edit .env: set LLM_API_KEY to your real Gemini key at minimum
```

**Backend + infra** (Postgres, MongoDB, Redis, RabbitMQ, agent-core,
job-worker, job-worker-beat, notify):

```bash
docker compose up -d postgres mongo redis rabbitmq
cd shared && pip install -e . && alembic upgrade head && cd ..
docker compose up -d --build
```

```bash
curl localhost:8000/health   # agent-core liveness
curl localhost:8000/ready    # checks Postgres/Mongo/Redis
curl localhost:4000/health   # notify
curl localhost:4000/ready    # checks Redis/Mongo
```

**Frontend** (dev-native, not containerized — runs against the backend's
published Docker ports over localhost):

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Defaults to `http://localhost:3000`. If that port's taken, Next.js falls
back to the next free one and tells you — when that happens, update
`.env`'s `FRONTEND_URL` to match and restart `agent-core` (CORS and OAuth
redirects are scoped to that one origin, not `*`).

### Auth setup

Email+password works out of the box against the local Postgres. To
exercise Google login for real: create a Google OAuth client with redirect
URI `http://localhost:8000/auth/google/callback`, set
`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` in `.env`. GitHub connect exists
server-side (`/auth/github/connect`) but is currently not surfaced in the
frontend UI.

### Useful local endpoints

| URL | What |
|---|---|
| `http://localhost:3000` | The app |
| `http://localhost:8000/docs` | FastAPI's auto-generated API docs |
| `http://localhost:15672` | RabbitMQ management UI (guest/guest) |
| `http://localhost:8000/dev` | A dev-only click-through test harness for the backend API (pre-dates the real frontend) |

## Project structure

```
agent-core/   FastAPI app — routers, auth deps, the dev test harness
job-worker/   Celery worker entrypoint
notify/       Node.js WebSocket service
frontend/     Next.js app (App Router)
shared/       jobpilot_shared — models, db/mongo/redis clients, the
              LangGraph pipeline, Celery tasks, Alembic migrations
docs/         Design decisions, roadmap, and a full per-phase build log
```

## Further reading

- `docs/DESIGN_DECISIONS.md` — the full "why": UX flow, auth model,
  scalability design, service inventory, ideas borrowed/rejected from
  reference projects.
- `docs/ROADMAP.md` — phase-by-phase build log, including every scope
  correction made once a phase's actual requirements were traced through.
- `docs/PHASE_2_PLAN.md` through `docs/PHASE_6_PLAN.md` — a complete,
  unfiltered build log per phase: what was built, why, and the real bugs
  found during verification (not just the happy path).
- `CLAUDE.md` — standing engineering rules for this repo (rate limiting,
  shared-package conventions, migration driver setup, etc.).
