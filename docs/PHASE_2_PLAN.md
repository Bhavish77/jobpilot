# Phase 2 — Graph & Multi-Agent Supervisor: implementation plan

Working doc for the current phase — finer-grained than `ROADMAP.md`, updated
as we go so progress survives across sessions. Delete or archive once Phase 2
ships (v0.3).

**Goal, from ROADMAP.md**: rebuild the chatbot as a LangGraph `StateGraph`;
conditional edges on resume quality. Supervisor + Resume / Cover Letter /
Interview Prep agents — Interview Prep parallel, Cover Letter sequential
after Resume. A drafter→reviewer critique-and-revise pass after each draft
(borrowed from `ai-job-search`). Cross-session memory + checkpointing in
Postgres; human-in-the-loop approval step.

**Working process for this phase**: 2–3 files per chunk, stop and explain
before moving to the next chunk. Each chunk should be independently testable
— no chunk should leave the app in a broken state.

## Chunks

- [x] **1. Minimal single-node graph** — replace `/chat`'s direct LLM call
      with the smallest possible LangGraph graph (one node, same behavior).
      No agents, no routing yet — just the plumbing and vocabulary
      (`StateGraph`, node, edge, state reducer).
      Files: `agent-core/app/graph/__init__.py`, `agent-core/app/graph/graph.py`,
      edit `agent-core/app/routers/chat.py`.
- [x] **2. Resume-quality gate** — a *new, separate* graph for the actual
      "Prepare" pipeline (not the same graph as `/chat`), with one
      conditional edge: is the user's stored resume substantial enough to
      generate from? If not, halt with a reason instead of generating from
      near-nothing. This is the roadmap's "conditional edges on resume
      quality" — a narrow, deterministic check, not a general-purpose
      routing supervisor (see below, "why no supervisor").
- [x] **3. Resume Agent** — one-shot generation from the stored `Resume`
      row + a job description. No memory needed — not a conversation.
- [x] **4. Cover Letter Agent** — one-shot, sequential after Resume;
      references what the Resume Agent emphasized.
- **5. Interview Prep Agent** — the *only* piece that's genuinely a
      multi-turn conversation (ask a question, evaluate the answer, ask the
      next one). Split into sub-chunks since it bundles too much for one
      pass:
  - [x] **5a. Postgres checkpointing infrastructure** — proven on a
        placeholder node (`interview_turn` in `interview_graph.py`) before
        any real logic exists, same pattern as chunk 2→3. New: a
        `checkpointer_conninfo` settings property (a *third* form of the
        Postgres URL — psycopg's pool wants a plain `postgresql://`, no
        SQLAlchemy dialect prefix); a FastAPI `lifespan` that opens an
        `AsyncConnectionPool`, builds an `AsyncPostgresSaver`, calls
        `.setup()` (creates LangGraph's own checkpoint tables —
        `checkpoints`/`checkpoint_writes`/`checkpoint_blobs`/
        `checkpoint_migrations` — entirely separate from Alembic/
        `models.py`, confirmed via `\dt`), and compiles the graph with that
        checkpointer attached; `POST /interview/turn`, which namespaces the
        client-supplied `thread_id` by the authenticated user's id
        (`f"{user.id}:{thread_id}"`) so one user can't read another's
        conversation by guessing their thread id. **Verified**: same
        thread_id recalled a fact ("Rust") across two separate HTTP
        requests; a third request (different thread_id, to check
        isolation) hit Google's free-tier quota (429, not our bug) before
        completing — not retried, since same-thread recall already proves
        the mechanism and different-thread isolation is guaranteed
        structurally (a different config key has no prior checkpoint row
        to find), not something that needs a live call to confirm.
  - [x] **5b. Real Interview Prep logic** — replaced the placeholder with
        `generate_curriculum` (gap analysis: original profile `Resume` vs.
        JD, never the tailored `resume_output`) and a real `interview_turn`
        that asks questions informed by the curriculum. New migration
        `a1b2c3d4e5f6` adds `Application.interview_curriculum` (first real
        migration since the initial one — that one's now applied to actual
        data, so this is additive, not an edit). New `app/applications.py`
        — shared `get_or_create_application`, reusable by chunk 9 for
        `/prepare` too. Router now takes `job_posting_id`/`job_description`
        instead of a client-chosen `thread_id`; derives
        `f"{user.id}:{application.id}"` instead, per the earlier
        discussion. Conditional edge from START (`_needs_curriculum`) skips
        regenerating the curriculum on turn 2+ — same narrow,
        deterministic-check pattern as chunk 2's resume-quality gate, not a
        router.
        **Verified**: curriculum generation succeeded and produced a
        genuinely good gap analysis (correctly flagged Kafka/Kubernetes/AWS
        as real gaps against a Flask/Postgres-only resume, correctly did
        *not* flag Python since that was actually present) — confirmed by
        reading the raw checkpoint row, not just trusting the HTTP
        response. Also verified something not tested before: that
        checkpointing survives a *partial* failure — the overall request
        failed with a Gemini 429 on the second (conversational) LLM call,
        but the first call's result (the curriculum) was already
        checkpointed and did not need regenerating on retry — confirmed by
        checking which node the retry's traceback failed in
        (`interview_turn`, not `generate_curriculum`). A full 200 with an
        actual interview question is blocked by Google's real free-tier
        daily quota (20 requests/day for this model) being exhausted from
        cumulative testing today — not a bug, not being retried further.
        Found and fixed one real gap while here: this router didn't wrap
        `graph.ainvoke` in a try/except like `chat.py`/`prepare.py` do, so
        the failure surfaced as a raw unhelpful 500 instead of a clean 502.
- [x] **6. Wire Interview Prep's curriculum generation to run in parallel**
      with the Resume → Cover Letter chain. Real finding before building
      this: the roadmap's "Interview Prep parallel" phrasing predates our
      revision, when Interview Prep was still a one-shot "generate
      questions" task — the same shape as Resume/Cover Letter, so a clean
      three-way fan-out made sense. Our revised Interview Prep has two
      different parts: `generate_curriculum` (one-shot, genuinely fits
      "parallel") and the ongoing conversation (open-ended, can never
      "join" a fan-in). Resolved: only `generate_curriculum` moved into
      `prepare_graph`'s fan-out (`_route_after_quality_check` now returns
      `["draft_resume", "generate_curriculum"]` — a list, which is what
      actually triggers LangGraph's concurrent scheduling, no explicit join
      node needed since `ainvoke` doesn't return until every branch reaches
      END). `interview_graph` simplified back to a single node —
      `interview_turn` now requires the curriculum to already exist
      (reads `Application.interview_curriculum`, persisted by `/prepare`)
      instead of chunk 5b's lazy generate-or-skip; `/interview/turn` 409s
      clearly if `/prepare` was never run for that job. `/prepare` now also
      persists `resume_output`/`cover_letter_output`/`interview_curriculum`
      onto the `Application` row — folds in the part of chunk 9's scope
      that was just "persist what Prepare produces," using the same
      `get_or_create_application` helper `/interview` already used.
      **Verified**: the free (no-LLM) precondition check — `/interview/turn`
      correctly 409s when `/prepare` was never called for that job. The
      full LLM path is blocked by today's exhausted Gemini quota (still the
      same 20/day free-tier cap from chunk 5b, not a new issue) — confirmed
      instead that a failed fan-out run persists *nothing* (checked
      directly in Postgres), since `prepare_graph` has no checkpointer,
      unlike `interview_graph`'s demonstrated partial-failure resilience —
      a real, deliberate asymmetry between the two graphs, not a bug.
- [x] **7. Drafter → reviewer critique-and-revise** — one combined
      `review_and_revise` node (not two separate per-artifact calls, to
      keep quota usage down) after `draft_cover_letter`, checking both
      resume and cover letter together for missed JD keywords, weak
      phrasing, and resume/cover-letter inconsistency. Same hard-line
      guardrail as the Resume Agent applies here too — a review pass can
      fabricate just as easily as the original draft. Output parsed via a
      literal `===RESUME===`/`===COVER_LETTER===` delimiter rather than
      JSON mode; falls back to keeping the original drafts untouched if the
      model doesn't follow the format, rather than risking a bad parse.
      **Verified end-to-end, fully successful this time** (quota had reset
      after the week-long gap): status came back `"reviewed"` (delimiter
      parsing worked), guardrails held through the review pass (still
      placeholder `[Name]`/`[Employer]`/`[Degree]`, nothing fabricated),
      and the curriculum output was genuinely sharp — correctly found few
      gaps for a strong-match candidate, then reasoned past the literal JD
      text to a real implicit domain gap (fintech transactional
      safety/idempotency) with a properly scoped project around it.
- [x] **8. Human-in-the-loop approval step.** Real finding before building:
      literally nothing in `prepare_graph` warrants an interrupt — every
      node just generates text and writes it to our own DB; the actual
      consequential action (submitting the application) happens entirely
      outside the graph, and the product's "prepare-only" design already
      guarantees human review via the normal Pipeline/Job-Workspace flow.
      Built anyway, scoped down, as a genuine learning exercise: gates
      `review_and_revise`'s output specifically — the graph now pauses
      after reviewing, shows the user both the original draft and the
      AI's proposed revision, and waits for an explicit accept/reject
      before either becomes final.
      Required splitting the reviewer into two nodes (`review_and_revise`,
      `await_review_approval`) — LangGraph re-runs a node from scratch on
      resume, so the expensive LLM call and the `interrupt()` call can't
      share one node without re-paying for the LLM call on every approval.
      Also required attaching a checkpointer to `prepare_graph` for the
      first time (pause-and-resume across two separate HTTP requests needs
      persisted state) — reuses the *same* checkpointer/pool `interview_graph`
      already has, with a `:prepare` thread_id suffix to avoid collision.
      New endpoint: `POST /prepare/{job_posting_id}/approve`.
      **Verified end-to-end**: first call correctly returned
      `"pending_review"` with both original and proposed text, nothing
      persisted yet; `/approve` with `{"decision": "accept"}` resumed
      correctly and persisted the *proposed* (not original) text; confirmed
      via raw checkpoint inspection that `review_and_revise`'s expensive
      call did not re-run on resume (identical state-version hash before
      and after resume).
- [x] **9. End-to-end test through the dev harness.** Added Prepare and
      Interview Prep sections to `agent-core/app/static/index.html` —
      job_posting_id/job_description inputs, a "Run /prepare" button, an
      accept/reject review step that shows once the graph pauses on
      `pending_review`, and an Interview Prep message box. Verified the
      harness's exact request shape matches the backend (free check: the
      409 precondition fires correctly through it) — didn't re-run the full
      LLM pipeline again here since chunks 6–8 already proved it
      end-to-end today; re-running would just spend quota for no new
      signal. The harness itself is what's left for a human click-through,
      which is the actual point of this chunk.

**Phase 2 complete — all 9 chunks done.**

## Decisions made along the way

- **No general-purpose "supervisor" node.** Traced through the actual
  documented UX (Profile upload → Discover → "Prepare" button → Job
  Workspace) and found no screen where a chat message needs to be
  classified into "which agent should handle this" — "Prepare" always
  triggers the exact same fixed pipeline (Resume → Cover Letter chained,
  Interview Prep parallel). That's a plain DAG, not a routing decision. The
  one real conditional in the roadmap ("conditional edges on resume
  quality") is a narrow, deterministic gate, not an LLM-driven router.
  A routing supervisor would only matter if free-form chat were expected to
  *trigger* the pipeline — it isn't, per the documented design.
- **Checkpointing moved from chunk 2 to chunk 5 (Interview Prep).** Traced
  through which screens actually need multi-turn memory: Resume and Cover
  Letter are one-shot document generation (no conversation); only Interview
  Prep is inherently back-and-forth ("delivered as a chat UI," per the
  design doc). The old Phase-1 `/chat` endpoint doesn't map to any
  documented screen — it's dev-testbed scaffolding, not a validated product
  feature — so it isn't getting memory added just for its own sake.
- **The Prepare pipeline is a separate graph from `/chat`'s graph.** They
  serve different, unrelated triggers (a button vs. a chat message) and
  don't share state — no reason to force them into one graph.
- **Resume Agent tailors aggressively; guardrail tightened once after a
  real test caught it overreaching.** Originally the prompt forbade
  inventing anything not in the source resume at all. Revised: JDs
  routinely inflate requirements, so aggressive framing/reordering/emphasis
  of real experience is fine, including adding relevant tools/technologies
  not literally in the source (Kubernetes, AWS, gRPC, Docker, CI/CD) —
  deliberate "willing to learn" framing. But testing chunk 4 showed the
  model also inventing a *second employer* with its own fabricated metrics
  ("99.9% uptime," "40% faster API responses") from a one-role source
  resume — that's different from framing, there's nothing to study up on
  for a job that never happened. Tightened further: never invent a second
  job/employment period, or any specific number not present in the source.
  Re-tested once after the fix (fabricated job and metrics gone, tech
  additions still present as intended); not testing further beyond that —
  Gemini's free tier is expected to be inconsistent, good enough is good
  enough for a personal project. This only works because of the next
  decision below.
- **Interview Prep (chunk 5) reads the original profile `Resume` row, never
  the per-job tailored `resume_output`.** The tailored resume is allowed to
  play to the JD; the untailored profile resume stays the honest source for
  gap analysis. Planned shape: compare profile resume vs. JD → classify
  each requirement as "candidate has it" / "doesn't have it at all" → turn
  real gaps into a learning curriculum (with projects, not just links) →
  generate practical interview questions from that analysis → run as a
  conversational prep session. Meaningfully richer than the original
  roadmap line ("generates likely questions and answers").
  **Resolved**: the curriculum persists — same pattern as `resume_output`/
  `cover_letter_output` on `Application`, a new column (exact name TBD when
  chunk 5 starts) added via a *new* Alembic migration (the initial one is
  now actually applied to real local dev data across many sessions, so from
  here on schema changes are additive migrations, not edits to that file).
  Job Workspace gets a Curriculum section alongside Resume/Cover
  Letter/Interview Prep. No submission/grading flow — see
  `DESIGN_DECISIONS.md`, "Interview Prep's curriculum stays guidance-only,"
  for why that's a deliberate, durable scope boundary, not just deferred.
- **LLM provider swap uses LangChain's own `init_chat_model`, not a
  hand-rolled factory.** First pass was a manual if/elif in `get_llm()`
  branching on `settings.llm_provider`. Replaced with LangChain's built-in
  `init_chat_model("provider:model", api_key=...)`, which parses the
  provider prefix, dynamically imports the right integration, and — nicer
  than the hand-rolled version — unifies the API-key kwarg name across
  providers (no more remembering `google_api_key` vs. `api_key` vs.
  `anthropic_api_key`). One consequence: `LLM_PROVIDER` must now be
  LangChain's own provider key, not a friendly name — Gemini-via-AI-Studio
  is `google_genai`, not `google` (updated in `.env`/`.env.example`/
  `config.py`). Needs the full `langchain` package now, not just
  `langchain-core` (added to `agent-core/requirements.txt`). Every node
  still only depends on the common `BaseChatModel` interface, so this swap
  touched exactly one file (`llm.py`) plus config defaults.

## Open questions / deferred

- Whether the graph runs synchronously inside the HTTP request (Phase 2) or
  gets wrapped in a Celery task (Phase 4) — current read of the roadmap is
  Phase 2 stays synchronous; Phase 4 is where the real async
  chain/group/chord orchestration from `tasks.py` takes over. **Resolved
  for Interview Prep specifically**: only the one-shot *start* of Interview
  Prep (gap analysis + curriculum + initial questions) is queue-worthy, same
  category as Resume/Cover Letter — every conversational *turn* after that
  stays synchronous request/response (`POST /interview/turn`, already built
  this way in chunk 5a), because queueing a turn wouldn't remove the wait
  the user is already expecting, just add indirection around it. Streaming
  a turn's reply token-by-token (not queueing) is the right future fix if
  per-turn latency ever becomes a real complaint — not needed now.
- There's no resume-upload endpoint yet (the `Resume` table has existed
  since Phase 1 but nothing writes to it). Chunk 2 will test the quality
  gate against a manually-inserted row rather than building that endpoint
  now — flagging it as a real gap, likely belonging to whichever phase
  builds the Profile/data-intake screen.
