# JobPilot — Design & Architecture Decisions

Living record of the product/UX/systems-design decisions made before and
during the build. This is the reference to re-read at the start of a new
session before making an architectural change. See `../CLAUDE.md` for the
condensed "standing rules" version and current phase status, and
`ROADMAP.md` for the phase-by-phase build plan.

## What JobPilot is

One project, not two. It merges a GenAI-engineer flagship project (LangGraph
multi-agent job-application assistant) with a full backend-engineering
curriculum (polyglot services, two databases, queues, resilience patterns,
AWS, observability, security) — built inside JobPilot instead of as a
separate toy app. No fixed timeline; depth over speed.

**Core loop:** user connects their data (resume/experience, optionally
GitHub repos) →
JobPilot finds and ranks relevant job postings → user picks jobs and hits
"Prepare" → a supervisor agent fans out to specialist agents (resume
tailoring, cover letter, interview prep) grounded in the user's real
background via RAG → user reviews the generated materials and self-reports
when they've applied. **JobPilot never auto-submits applications** — it
prepares, the human applies. This was an explicit choice (AskUserQuestion →
"Prepare only, user submits").

## Product scope decisions

- **Auto-apply vs prepare-only:** Prepare-only. JobPilot's job is to produce
  a tailored resume, cover letter, and interview prep — not to submit forms
  on job boards. The user applies themselves and marks the job "Applied."
- **Interview Prep Agent:** Generates likely questions *and* answers
  grounded in the JD + candidate background, delivered as a chat UI the user
  can interact with (not just a static Q&A doc). A WebRTC voice-mode version
  (agent asks questions out loud, listens to spoken answers) is a named
  stretch goal, not v1.
- **Auth is provider-agnostic; GitHub is optional, not login** (revised —
  see "Auth model" below for the original design and why it changed).
- **API key model (BYOK vs managed) — hybrid, deferred to Phase 10:**
  - Users can either bring their own LLM API key (BYOK) or use JobPilot's
    own backend-managed key.
  - Free/paid **plans gate quotas and model choice** regardless of key mode.
  - Rate limiting/concurrency protection still applies **even under BYOK** —
    not to protect a shared token budget (that's the user's own provider
    account), but to protect JobPilot's own infrastructure and to guard
    against runaway agent loops burning the user's key. (Clarified because
    the first instinct was "if BYOK, rate limiting disappears entirely" — it
    doesn't; only the *quota-sharing* reason disappears, the
    *infra-protection* and *safety-net* reasons remain.)
  - v1 ships with a single managed key and no plans; BYOK + tiers land in
    Phase 10 once the core product works.

## Auth model — email/password + Google, GitHub optional (revised)

Original Phase 1 design: GitHub OAuth did double duty as both login and RAG
data-source consent — one handshake, `repo` scope requested up front. Revised
once the product scope widened from "developers" to "any job seeker": most
job seekers don't have, or want to use, a GitHub account to sign in.
Continuing to gate login behind GitHub would have meant most of the
addressable audience couldn't create an account at all.

**New model:**
- **Sign-in**: email+password (`POST /auth/register`, `POST /auth/login`,
  bcrypt-hashed) or Google OAuth (`GET /auth/google/login`) — either is a
  complete, standalone way to use JobPilot.
- **Account linking**: if someone registers with email+password and later
  signs in with Google using the same email, the Google callback links
  `google_id` onto the existing user row instead of creating a duplicate
  account (matched by email — see `agent-core/app/routers/auth.py`).
- **GitHub is a connection, not a login path**: `GET /auth/github/connect`
  (from the profile screen, requires an existing session) links `github_id`
  onto the already-logged-in user, purely to grant Phase 3's RAG ingestion
  read access to their repos. A user who never connects GitHub still gets
  the full product minus repo-based RAG grounding — the resume text they
  upload directly still feeds RAG.
- Session mechanics are unchanged from the original design: whichever path
  succeeds mints our own short-lived JWT, set as an httpOnly cookie. Third-
  party tokens (Google's, GitHub's) never reach the frontend.

## UX flow — the model that stuck (after one correction)

Two screens were originally conflated; the fix is now the standing rule (see
`CLAUDE.md`):

- **Discover** = browsing only. A ranked list of matching jobs, each with a
  match score, an expandable inline JD (no navigation), a checkbox for
  multi-select, and a per-card "Prepare" button. Selecting jobs and clicking
  **Prepare applications** is the *only* thing that starts the agent
  pipeline for those jobs. Discover never shows resume/cover-letter/
  interview-prep content directly.
- **Pipeline** = tracking, for jobs that have started the process. Board
  columns: **Preparing → Ready to apply → Applied → Interviewing.** Clicking
  a card here opens the **Job Workspace**.
- **Job Workspace** = the only place with the three tabs (Overview / Resume
  / Cover Letter / Interview Prep chat) for one specific job, reachable only
  from a Pipeline card.

Mental model: *Discover decides what to start. Pipeline tracks what's
started.* A working interactive mockup of this exists as a Claude artifact
("JobPilot Screens") — ask Bhavish for the link.

Dashboard shape: a persistent sidebar (profile/data-connections, plan usage)
+ the main screens above. Profile/data-intake is where resume upload + GitHub
repo connection happens, once, before Discover has anything to rank.

## Why background jobs need a queue (not a synchronous request)

Naive version considered and rejected: "send user data + prompt to the LLM,
get output, make a PDF, send it back" — synchronously, inside the HTTP
request. Breaks once more than a handful of users act at once, because LLM
calls are slow (seconds) and hit a flaky external dependency you don't want
tying up a web request/connection, and because resume/cover-letter/interview
-prep are three units of work with real ordering constraints — a workflow,
not a single call.

**Ordering:** Resume → Cover Letter run **sequentially** (cover letter
references what the resume emphasized). Interview Prep runs **in parallel**
(only needs the JD + candidate background). Maps onto Celery primitives: a
`chain(resume_task, cover_letter_task)` combined with a
`group([interview_prep_task])`, wrapped in a `chord` for whatever should run
after all three finish (mark "Ready to apply", fire the notification). See
`shared/jobpilot_shared/tasks.py` for the Phase-1 placeholder shape of this.

**Frontend updates:** polling and queuing are separate concerns. Hybrid: one
GET on page load (so a refresh isn't blank) + a WebSocket connection (the
**Notify** service) for live push — no continuous polling.

## Scaling one workflow to ~500 concurrent users

Framed around being able to discuss it confidently in interviews, not
because JobPilot needs this scale today.

- **Distributed rate limiting mirrors the real provider quota.** A single
  Redis token bucket, shared across *all* workers (not one per worker),
  sized to the actual LLM provider RPM/TPM contract. Implemented in Phase 1
  as `acquire_llm_permit()` — verified atomic under concurrency (20
  simultaneous acquires against a 5-token bucket granted exactly 5, no
  double-spend).
- **Worker count is capped by quota, not the other way around.** Once
  request-rate is quota-gated, more Celery workers past that point just
  contend for the same shared bucket instead of raising real throughput.
- **The "last token" race condition:** two workers can't both read "1 left"
  and both proceed. Fix: an atomic Redis op — `DECR` for a simple counter, or
  a Lua `EVAL` script for real token-bucket-with-refill (what Phase 1 uses) —
  so check-and-decrement happens as one atomic unit. Same class of bug, same
  fix shape, as the Postgres optimistic-locking `version` column on
  `applications` (see `shared/jobpilot_shared/models.py`).
- **Multi-tenant fairness (free vs. paid), layered, not just "bigger number
  for paid":** per-user concurrency caps; separate/priority queues;
  **dedicated worker pools per tier (bulkhead)**; **partitioned token-bucket
  budgets** between tiers. All deferred to Phase 10 alongside BYOK.
- **Explicitly right-sized, not over-engineered:** Mongo sharding and a
  distributed WebSocket presence registry are deliberately *not* built at
  this scale — naming why you're skipping a pattern is as much a signal as
  building one.

## Service inventory

**4 deployable services:**
1. **Agent Core** (FastAPI, Python) — auth, LangGraph supervisor + specialist
   agents, RAG, the API the frontend talks to.
2. **Job Worker** (Celery, same codebase as Agent Core's `shared` package,
   different deployment target/entrypoint) — job-search ingestion, the
   prepare-application pipeline, wrapped in circuit breakers/retries/timeouts.
3. **Notify** (Node.js) — per-user WebSocket connections, subscribes to
   Redis pub/sub, pushes live updates, logs events to Mongo.
4. **Frontend** (Next.js) — the dashboard UI. Not built yet (Phase 6).

**Managed infrastructure:** Postgres, MongoDB, Redis, RabbitMQ, a vector
store (Chroma to start, pgvector documented as the trade-off), S3.

**Flagged future split:** once ingestion and the prepare-application
pipeline compete for worker capacity, Job Worker splits into two fleets
(ingestion vs. pipeline workers). Not needed at v1.

## GitHub repo ingestion strategy (Phase 3 planning note)

Discussed before Phase 3 starts, so it doesn't get re-litigated: README-only
ingestion was the original v1 sketch, but a README is often the weakest
signal — many repos have none, or a stale placeholder. Layered plan, cheapest
first: (1) repo metadata from the GitHub API (description, topics, language)
— free, always available; (2) the manifest file if one exists
(`package.json`, `requirements.txt`, etc.) — more objective than a README's
self-description; (3) the README, but only if it has real content (skip
anything under a few dozen words); (4) as a stretch, a selective slice of
actual source (entry-point files, or the most-committed files) — real code
signal, but needs its own chunking strategy since code and prose embed
differently (already flagged in the RAG phase notes below). Don't fake a
summary from a bare file tree when there's no README — fall back to
metadata + manifest instead.

## Considered and explicitly declined: ideas from a similar OSS project

Bhavish found `kalpthakkar/JobPilot-AI` on GitHub (a solo project, real repo —
177 commits, not just an aspirational README) and we discussed borrowing
ideas from it. Decision: **not pursuing any of them right now** — noted here
so they don't get silently re-proposed later:
- Gmail-based application-status tracking (read confirmation/interview
  emails to auto-advance Pipeline stages).
- An analytics dashboard over the application funnel (response rate,
  time-to-response).
- Hybrid model routing (free local embeddings via Ollama/sentence-transformers
  for RAG, reserving the paid/managed LLM budget for generation calls only).
- Explicitly rejected regardless of interest level: their core
  feature — Selenium-driven automated application *submission* — contradicts
  the prepare-only decision above and carries real ToS risk. Don't add it.

## Borrowed ideas from another OSS reference: `MadsLorentzen/ai-job-search`

A Claude-Code-native job-search workflow (slash commands + skills, runs
locally, no server) — different shape from JobPilot (standalone multi-user
web app), but its `/apply` pipeline has patterns worth adopting once JobPilot
reaches the equivalent phase. Adopting:
- **PDF compile-and-visually-inspect loop** (Phase 4, resume/cover-letter
  generation): don't trust that LaTeX/PDF output *looks* right just because
  it compiled — render it and check for orphaned entries, overflow, spacing,
  before presenting it to the user.
- **ATS text-layer verification** (Phase 4): extract the generated resume
  PDF's text layer the way an ATS parser would (not just eyeball the
  rendered page) and verify contact details are present as real text, in
  sane reading order, before calling generation done.
- **Relevance-weighted content cutting** (Phase 2/4, Resume Agent): when a
  generated resume overflows its page limit, don't trim from the bottom
  mechanically — score each line by relevance to the target posting,
  uniqueness, and whether the cover letter depends on it, and cut the
  lowest-scoring line first.
- **Drafter → reviewer critique-and-revise step** (Phase 2): after a
  specialist agent (Resume/Cover Letter) produces a draft, a second pass
  critiques it before it's marked ready — catches missed keywords and weak
  framing a single generation pass leaves in. Folds into the supervisor
  design rather than requiring a new agent role.

**Explicitly not adopting**, because it's already covered by the standing
decision above: Gmail-based application-status tracking and an analytics
dashboard over the funnel — `ai-job-search` has both (`/gmail-sync`,
`/html-report`); JobPilot already considered and declined this exact category
of feature when reviewing `kalpthakkar/JobPilot-AI`. Noted here so it doesn't
get silently re-proposed just because a second project happens to have it.

## Status

Phase 0 (mono-repo scaffold + docker-compose data layer) and Phase 1 (auth —
email+password + Google, GitHub as an optional connect-later flow — Postgres
schema + Alembic migration, basic LangChain `/chat` gated by the rate
limiter, cache-aside `/jobs`) are built. The original GitHub-only version of
Phase 1 was verified against a real local Postgres + Redis; the auth rework
above hasn't been re-run against a live DB yet. Next: **Phase 2** — LangGraph
`StateGraph`, supervisor + three specialist agents (plus the
drafter/reviewer critique step noted above), checkpointing in Postgres.
