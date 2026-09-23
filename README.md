# JobPilot

An AI job-search and application-prep assistant, built as one mega-project to cover
frontend + backend + AI + systems design in a single, real, polyglot system. It
never auto-submits applications — it prepares tailored resumes, cover letters, and
interview prep, and the user applies themselves.

Full design record (product/UX decisions, scalability design, service inventory):
see the "JobPilot — Design & Architecture Decisions" doc.
Full learning checklist + phased build plan: see the "JobPilot" artifact.

## Services

| Service | Language | Role |
|---|---|---|
| `agent-core/` | Python (FastAPI) | Auth, LangGraph supervisor + specialist agents, RAG, the API the frontend talks to |
| `job-worker/` | Python (Celery) | Job-search ingestion + the prepare-application pipeline (resume/cover-letter/interview-prep tasks), wrapped in circuit breakers/retries/timeouts |
| `notify/` | Node.js | Holds per-user WebSocket connections, subscribes to Redis pub/sub, pushes live updates |
| `frontend/` | Next.js | Dashboard UI (Profile / Discover / Pipeline / Job Workspace) — built in Phase 6 |
| `shared/` | Python package | Config, DB/Mongo/Redis clients, Celery app + task definitions — imported by both `agent-core` and `job-worker` so they run one codebase on two deployment targets |

Managed infrastructure (not application code): Postgres, MongoDB, Redis, RabbitMQ,
a vector store (Chroma to start), S3.

## Phase 0 — scaffold

- [x] Mono-repo: `agent-core/`, `job-worker/`, `notify/`, `frontend/`
- [x] Docker Compose spinning up Postgres, MongoDB, Redis, RabbitMQ together
- [ ] Read GIL + Node event-loop fundamentals before writing service code

## Phase 1 — Agent Core v1: auth, chat, cache

- [x] Email+password (`POST /auth/register` / `POST /auth/login`) and Google
      OAuth (`/auth/google/login` → `/auth/google/callback`) login — works for
      any job seeker, not just developers
- [x] GitHub as an optional, later connection (`/auth/github/connect`, from
      the profile screen) purely to grant Phase 3's RAG ingestion read access
      to the user's repos — never required to use JobPilot
- [x] Postgres schema — `users`, `resumes`, `applications` (Alembic migration,
      `shared/migrations/versions/`)
- [x] Basic LangChain chatbot (`POST /chat`), gated by the token-bucket limiter
- [x] Redis cache-aside for job listings (`GET /jobs`) — mock data until Phase 4's
      real ingestion exists; the caching mechanics are real
- [x] Redis-backed token-bucket rate limiter (`acquire_llm_permit`) — verified
      atomic under concurrency: 20 simultaneous callers against a 5-token bucket
      granted exactly 5, no double-spend on the last token

## Running it locally

```bash
cp .env.example .env
docker compose up -d postgres mongo redis rabbitmq   # data layer
```

Apply the schema:

```bash
cd shared
pip install -e .
alembic upgrade head
cd ..
```

Bring up the app services:

```bash
docker compose up -d --build
```

Health checks:

```bash
curl localhost:8000/health   # agent-core liveness
curl localhost:8000/ready    # agent-core readiness — pings Postgres/Mongo/Redis
curl localhost:4000/health   # notify
```

Email+password login works out of the box against the local Postgres — no
external setup needed. To exercise Google login, set `GOOGLE_CLIENT_ID`/
`GOOGLE_CLIENT_SECRET` in `.env` from a Google OAuth client (redirect URI
`http://localhost:8000/auth/google/callback`), then visit
`http://localhost:8000/auth/google/login` in a browser. GitHub is optional —
connect it later (once logged in) via `http://localhost:8000/auth/github/connect`
using a GitHub OAuth App with callback `http://localhost:8000/auth/github/callback`,
needed only once Phase 3's RAG ingestion is being tested.

RabbitMQ management UI: http://localhost:15672 (guest/guest by default).

## Next up

Phase 2 — rebuild the chatbot as a LangGraph `StateGraph`: a supervisor plus
Resume / Cover Letter / Interview Prep specialist agents, with cross-session
memory and checkpointing persisted in Postgres.
