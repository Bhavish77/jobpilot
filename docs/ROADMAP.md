# JobPilot — Build Roadmap (offline copy)

Condensed phase-by-phase plan. The interactive version (checkbox-tracked,
with interview-flashcard QA under each phase) is a Claude artifact — ask
here is the link if you want that version. No day counts anywhere on
https://claude.ai/artifact/QZ2GA8BqvK9rTdxwFEHQ8S
purpose — go at whatever pace the depth deserves.
here 

Status legend: ✅ done and verified · 🔜 next up · ⬜ not started

## ✅ Phase 0 — Scaffold
Mono-repo (`agent-core/`, `job-worker/`, `notify/`, `frontend/`, `shared/`),
docker-compose for Postgres/MongoDB/Redis/RabbitMQ.

## ✅ Phase 1 — Agent Core v1: auth, chat, cache
Email+password and Google OAuth login (works for any job seeker, not just
developers); GitHub is a separate, optional `/auth/github/connect` made later
purely for Phase 3's RAG ingestion — never required to use JobPilot. Postgres
schema (users, resumes, applications) via Alembic, basic LangChain `/chat`
gated by the Redis token-bucket rate limiter, cache-aside `/jobs` (mock data
until Phase 4). *(Reworked from the original GitHub-only login — see
`docs/DESIGN_DECISIONS.md`, "Auth model" — not yet re-verified against a live
DB.)*

## 🔜 Phase 2 — Graph & multi-agent supervisor
Rebuild the chatbot as a LangGraph `StateGraph`; conditional edges on resume
quality. Supervisor + Resume / Cover Letter / Interview Prep agents —
Interview Prep parallel, Cover Letter sequential after Resume. A
drafter→reviewer critique-and-revise pass after each draft (borrowed from
`ai-job-search`'s `/apply` pipeline — see `docs/DESIGN_DECISIONS.md`).
Cross-session memory + checkpointing in Postgres; human-in-the-loop approval
step. **Ship v0.3.**

> Soft checkpoint: a multi-agent system with real auth and persisted state is
> already a legitimate interview story. No deadline forces starting to apply
> here, but the option is open — no need to wait for Phase 10.

## ⬜ Phase 3 — RAG: resume + GitHub
Chunk + embed resume/portfolio (works standalone — RAG doesn't require
GitHub). If the user has connected GitHub via `/auth/github/connect`,
ingestion layers in: metadata → manifest file → README (if it has real
content) → optionally a selective code slice (see
`docs/DESIGN_DECISIONS.md`'s ingestion-strategy note — don't just do
README-only). Chroma vector store, hybrid search (BM25 + dense), agentic RAG,
basic RAGAS-style eval. Stretch: same retrieval on pgvector, compare.
**Ship v0.4.**

## ⬜ Phase 4 — Job Worker: ingestion, Mongo, resilience, Saga
Celery + RabbitMQ pipeline; daily job-search agent (Adzuna/RemoteOK/
Arbeitnow). Raw postings → MongoDB as-is; normalization step scores + writes
clean rows to Postgres. Circuit breaker + retry/backoff/jitter + timeout
around every external call. Idempotent task design; optimistic-locking
version check on "apply to job" (the `Application.version` column already
exists). The prepare-application Saga: reserve credit → resume → cover
letter → compensate on failure. Generated-resume output gets the PDF
compile-and-inspect loop + ATS text-layer verification + relevance-weighted
overflow cutting (borrowed from `ai-job-search` — see
`docs/DESIGN_DECISIONS.md`). **Ship v0.5.**

## ⬜ Phase 5 — Notify: Node.js WebSocket service
WebSocket server per logged-in user; subscribe to Redis pub/sub events from
Agent Core / Job Worker (the skeleton for this already exists in
`notify/index.js`). Push "new match," "tailoring ready," "interview
reminder"; log events to MongoDB. Deliberately profile one blocking sync call
freezing every other connection, then fix it.

## ⬜ Phase 6 — Frontend
Next.js chat UI + application-pipeline dashboard (Discover / Pipeline / Job
Workspace, per the UI mockup artifact). Live updates via the Notify
WebSocket. **Ship v0.9.**

## ⬜ Phase 7 — Deploy to AWS, for real
EC2/Fargate for the three services; RDS for Postgres; MongoDB Atlas; S3 +
presigned URLs for resume/cover-letter PDFs, IAM roles not hardcoded keys;
SQS documented as a RabbitMQ alternative; VPC basics; CloudWatch; graceful
shutdown + `/live`/`/ready` on every service.

## ⬜ Phase 8 — Observability
Structured JSON logs with a correlation ID across all three services;
OpenTelemetry distributed tracing (Python + Node); Prometheus + Grafana.

## ⬜ Phase 9 — Testing & CI/CD
pytest unit + integration (mock the LLM and job-board APIs); Jest for
Notify; load test (k6/Locust) an agent endpoint specifically — latency is
model-call-bound, not CPU-bound; GitHub Actions: lint, test, build, deploy,
gated Alembic migrations.

## ⬜ Phase 10 — Security, multi-user hardening & plans
Per-user data isolation (Postgres RLS, namespaced vector collections); real
per-user quotas on top of the token bucket; prompt-injection defenses on
ingested job postings; secrets via env/secrets manager. Plus the deferred
product design: `key_mode` (BYOK vs managed), free/paid plan gates, dedicated
worker pool + partitioned token-bucket share per tier (bulkhead-based
fairness). **Ship v2.0.**

---

## The interview loop (applies throughout, not just at the end)

1. **Build** the piece.
2. **Explain unprompted** — what problem it solves, what breaks without it,
   where in JobPilot you made that call — right after building it, no notes.
3. **Mock interview, with pushback** — "what if the LLM call times out
   mid-retry," "why prefork over threads here."
4. **Gap-fill** — behavioral/STAR stories from JobPilot's real incidents (a
   deliberately-broken dependency, a load test that found the real ceiling).
