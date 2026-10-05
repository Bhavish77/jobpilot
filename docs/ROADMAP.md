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
`docs/DESIGN_DECISIONS.md`, "Auth model" — re-verified against a live DB:
register/login/me all tested end-to-end.)*

## ✅ Phase 2 — Graph & multi-agent supervisor
Rebuilt the chatbot as a LangGraph `StateGraph` (`app/graph/graph.py`). The
Prepare pipeline is a second, separate graph (`prepare_graph.py`): a
resume-quality gate (conditional edge — the roadmap's "no supervisor" item
turned out not to need one; see `docs/PHASE_2_PLAN.md` for why), real
Resume/Cover Letter agents (sequential), Interview Prep's curriculum
generation running in parallel with them (the *conversational* half of
Interview Prep stayed a separate, checkpointed graph — it can't join a
fan-in the way a one-shot task can), a drafter→reviewer critique-and-revise
pass (borrowed from `ai-job-search`), and a real human-in-the-loop
`interrupt()`/resume gate on the reviewer's proposed revision. Cross-session
Postgres checkpointing covers both graphs. Full chunk-by-chunk build log,
including the three places the original roadmap wording didn't survive
contact with the actual design, lives in `docs/PHASE_2_PLAN.md`. **v0.3.**

> Soft checkpoint: a multi-agent system with real auth and persisted state is
> already a legitimate interview story. No deadline forces starting to apply
> here, but the option is open — no need to wait for Phase 10.

## ✅ Phase 3 — RAG: resume + GitHub
**Scope cut down on inspection** — see `docs/PHASE_3_PLAN.md`. GitHub
ingestion deferred (explicit call). Resume-only RAG turned out to have no
real job to do either: a single resume is 5-15 chunks against a 1M-token
context window — dumping it whole (today's approach) costs nothing and
loses no signal, where retrieval over something this small could only drop
real information. Chunking/embeddings/vector store deferred alongside
GitHub, to be built together once an actual corpus justifies them. What's
real right now: `POST /resumes` — closing the manual-SQL-insert gap used
throughout Phase 2's testing. When RAG is eventually built: pgvector (not
Chroma — already run Postgres, nowhere near the scale where a dedicated
vector DB earns its keep), Gemini embeddings (same provider as generation),
structure-aware chunking (one chunk per resume section/job entry, not
fixed-size windows). Hybrid search and "agentic RAG" are further out
still — they solve problems that only appear once plain dense retrieval is
real and already insufficient.

## ✅ Phase 4 — Job Worker: ingestion, Mongo, resilience, Saga
**"Saga" scope-corrected on inspection** — see `docs/PHASE_4_PLAN.md`.
"Reserve credit" doesn't correspond to anything that exists (BYOK/credits
are deferred to Phase 10 on purpose); there's no credit to compensate and
no distributed side effect across independent services that a classic
Saga rollback model is needed for. The real resilience problem was wasted
work on retry — fixed by making `prepare_graph`'s routing resumable
(empirically confirmed a plain retry re-executed already-finished nodes
before the fix). Adzuna ingestion deferred (needs credentials nobody's
signed up for, same category of deferral as GitHub in Phase 3) — RemoteOK
+ Arbeitnow are the real sources. What shipped: Celery + RabbitMQ pipeline
(one task per pipeline, not four coordinated by `chain`/`group`/`chord` —
`prepare_graph`'s own edges already own that ordering); Celery Beat daily
ingestion; raw postings → MongoDB as-is, normalized + upserted → Postgres;
circuit breaker + retry/backoff/jitter around every external call;
resumable task routing; optimistic-locking "apply to job" endpoint on
`Application.version`; the PDF compile-and-inspect loop + ATS text-layer
verification + relevance-weighted overflow cutting (`WeasyPrint` +
`PyMuPDF`, wired into `prepare_graph` as a real node) borrowed from
`ai-job-search`. A real cross-event-loop asyncpg bug was found and fixed
along the way (`dispose_engine()` — see `docs/PHASE_4_PLAN.md`, chunk 4).
**Ship v0.5.**

## ✅ Phase 5 — Notify: Node.js WebSocket service
**Event scope corrected on inspection** — see `docs/PHASE_5_PLAN.md`. Of
the three named push events, only "tailoring ready" maps to anything that
exists: Phase 4 already built the moment `Application.status` flips to
`READY_TO_APPLY`. "New match" needs per-user job-matching/scoring that was
explicitly deferred at ingestion (Phase 4, chunk 2); "interview reminder"
needs a scheduled interview date/time that doesn't exist anywhere in the
schema. Both deferred — same category as every other roadmap item that
named a not-yet-built feature. What shipped: real session-JWT auth on the
WebSocket upgrade (same cookie/secret agent-core verifies, rejected with a
real `401` before the handshake completes if missing/invalid);
`publish_event()` wired into both places `tailoring_ready` actually fires;
every event logged to a MongoDB `notify_events` collection before the live
push, so there's a durable record even if nobody's connected; and the
roadmap's own "deliberately profile one blocking sync call" exercise,
done as a standalone script (`notify/blocking_demo.js`) that measured a
synchronous call freezing an unrelated connection to **2003ms**, then
**6ms** after moving the same work to a `worker_threads` Worker.

## ✅ Phase 6 — Frontend
**Designed fresh, not from the old "JobPilot Screens" mockup** (explicit
user choice). Three real backend gaps found and fixed before any screen
was built — `GET /jobs` was still Phase 1's hardcoded mock (never wired to
Phase 4's real `JobPosting` table), there was no `GET /applications` list
endpoint for Pipeline, and no CORS config existed for the frontend's
origin at all — see `docs/PHASE_6_PLAN.md`'s scope-correction section.
Stack: Next.js 15 (App Router, TypeScript) + Tailwind v4 + a shadcn/ui-
style `components/ui/` primitive library (Radix + `class-variance-
authority`, owned component code, not a black-box kit). Every color
pairing checked against the real WCAG 2.1 contrast formula, not
eyeballed — caught and fixed a real dark-mode contrast failure (white
text on the primary button only hit ~3:1) before it reached a screen.
Shipped: a landing page, email/password + Google auth, an auth-gated app
shell, Discover (real per-resume keyword match scores), Pipeline (the
real four-column board), the Job Workspace (resume/cover-letter/interview
-prep tabs, the pending-review accept/reject UI, Mark-as-applied), Profile
(resume upload, GitHub connect), and live updates over the real Notify
WebSocket. Verified against the real running stack end-to-end, including
one full real LLM pipeline run through the actual UI's data contracts —
which surfaced and fixed a second cross-event-loop bug (this one in the
shared Redis connection pool, same root cause as Phase 4 chunk 4's
Postgres bug, different resource — see `docs/PHASE_6_PLAN.md`). **Ship
v0.9.**

## 🔜 Phase 7 — Deploy to AWS, for real
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
