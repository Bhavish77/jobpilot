# Phase 4 — Job Worker: ingestion, Mongo, resilience, Saga — implementation plan

Working doc for the current phase, same spirit as `PHASE_2_PLAN.md`/
`PHASE_3_PLAN.md`. Delete or archive once Phase 4 ships.

**Goal, from ROADMAP.md**: Celery + RabbitMQ pipeline; daily job-search
agent (Adzuna/RemoteOK/Arbeitnow). Raw postings → MongoDB as-is;
normalization step scores + writes clean rows to Postgres. Circuit breaker
+ retry/backoff/jitter + timeout around every external call. Idempotent
task design; optimistic-locking version check on "apply to job". The
prepare-application Saga: reserve credit → resume → cover letter →
compensate on failure. Generated-resume output gets the PDF
compile-and-inspect loop + ATS text-layer verification + relevance-weighted
overflow cutting.

## Fixed before any Phase 4 work started

- [x] **Rate limiter never actually gated `/prepare`.** `chat.py` and
      `interview.py` correctly called `acquire_llm_permit()` once before
      their one LLM call each — `prepare.py` called it **zero times**,
      despite `prepare_graph` making 3-4 separate Gemini calls per run.
      Found by grepping every call site, a direct violation of CLAUDE.md's
      "every LLM call goes through `acquire_llm_permit()` first." Fixed by
      moving the enforcement into a shared `call_llm()` in
      `app/graph/llm.py`, used by every node (`draft_resume`,
      `draft_cover_letter`, `generate_curriculum`, `review_and_revise`,
      `graph.py`'s `generate_reply`, `interview_turn`) instead of each
      calling `get_llm().ainvoke()` directly — can't be forgotten again
      for a future node, since there's only one real call site left.
      Removed the now-redundant router-level checks from `chat.py`/
      `interview.py` (would have double-decremented against the new
      per-call enforcement). **Verified**: set the bucket to 2, ran
      `/prepare`, confirmed via the bucket's exact final value (0) and a
      clean 429 that exactly the two parallel calls succeeded before the
      third was correctly denied.

## Scope correction: the "Saga" needs to mean something different than written

Traced through what "reserve credit → resume → cover letter → compensate
on failure" actually requires, same discipline as every prior phase:

- **"Reserve credit" doesn't correspond to anything that exists.**
  CLAUDE.md is explicit: BYOK/plans/credits are deferred to Phase 10 on
  purpose — v1 has a single managed key, no credit system at all. There is
  nothing to reserve.
- **Checked empirically whether checkpointing already gives free recovery
  (it doesn't, for a plain retry).** `prepare_graph` gained a checkpointer
  in Phase 2 chunk 8 (for the interrupt feature) — after Phase 2 chunk 6
  tested "a failed run persists nothing" and found exactly that. Re-tested
  now that the checkpointer exists: forced a failure 3 calls into a run
  (resume + curriculum succeeded, cover letter denied), then retried the
  *same* job_posting_id once quota was available again. Checked the raw
  checkpoint version hashes for `resume_output`/`curriculum` across both
  attempts — they **changed** on retry, proving `draft_resume` and
  `generate_curriculum` were fully re-executed, not resumed. Checkpointing
  only skips re-running a node when you resume via `Command(resume=...)`
  at an actual pending interrupt (what `/approve` does) — a plain retry
  with fresh input restarts the whole graph from `START`, wasting whatever
  already succeeded.
- **The conclusion**: there's no credit to compensate, and no distributed
  side effect across independent services that a classic Saga's
  rollback-the-earlier-steps model is needed for — the only real
  resilience problem here is wasted work on retry, which is exactly what
  the roadmap's separate "idempotent task design" line already names. Fix
  that properly (below) and there's nothing left for a Saga pattern to do.
  Not building compensating-transaction logic for a credit system that
  doesn't exist.

## Chunks

- [x] **1. Make `prepare_graph` actually resumable on retry** — the real
      fix behind "idempotent task design." `_route_after_quality_check`
      now inspects `resume_output`/`cover_letter_output`/`proposed_resume`/
      a set of terminal review statuses (so a re-run after full completion
      can't re-trigger the interrupt) to resume the Resume->Cover
      Letter->Review chain from wherever it left off, and independently
      checks `curriculum` for the parallel branch — same idea as
      `interview_graph`'s `_needs_curriculum` check, extended to cover
      every step, not just one.
      **Verified**: attempted a live end-to-end retry test, but Gemini's
      daily quota (20/day) ran out mid-test with a 16-hour lockout —
      switched to testing the routing function directly instead, since
      it's pure Python with zero I/O and doesn't need a live LLM call to
      verify at all. Six constructed states covering every branch
      (fresh/partial/fully-done/quality-failed combinations) all routed
      exactly as designed, including the two trickiest cases: "fully
      done" returns straight to `END` rather than re-triggering the
      interrupt, and curriculum is correctly omitted once already present
      rather than being redundantly re-added. This is what makes Celery's
      own task redelivery (chunk 4 below) safe to actually retry without
      repaying for already-completed LLM calls.
- [ ] **2. Job model + ingestion task** — a real `JobPosting`-shaped
      Postgres table (replacing `jobs.py`'s mock data) and a Celery task
      that calls Adzuna/RemoteOK/Arbeitnow, writes raw postings to Mongo
      as-is, then a normalization step that scores and writes clean rows
      to Postgres. Scheduled daily via Celery Beat (not configured yet —
      new piece of infra).
- [ ] **3. Circuit breaker + retry/backoff/jitter + timeout** around the
      three external job-board calls specifically — this is squarely
      justified here (unlike past phases' false-starts): these are real,
      flaky third-party HTTP APIs, which is exactly the situation these
      patterns exist for. Likely `tenacity` for retry/backoff/jitter; a
      small hand-rolled circuit breaker (Redis-backed, so state is shared
      across worker processes — same reasoning as the rate limiter) to
      teach the mechanism rather than pull in a library for one concept.
- [ ] **4. Wrap `prepare_graph` in one real Celery task** — per the
      earlier design-doc revision (`docs/DESIGN_DECISIONS.md`, "Why
      background jobs need a queue"): one task invokes the whole graph,
      not four tasks coordinated by Celery's own chain/group/chord.
      `/prepare` changes from `await`ing the graph directly to
      `.delay()`-ing this task and returning immediately. Depends on
      chunk 1 — without resumable routing, Celery's `task_acks_late`
      redelivery-on-crash would hit the exact wasted-work problem just
      found.
- [ ] **5. Optimistic-locking "apply to job" endpoint** — `Application`
      already has the `version` column (Phase 1). Add the endpoint that
      actually uses it: read `version`, write the new status conditioned
      on `WHERE version = <version just read>`, reject as stale (409) if
      another update already landed first.
- [ ] **6. ATS/PDF verification loop** — borrowed from `ai-job-search` (see
      `docs/DESIGN_DECISIONS.md`): compile the generated resume to an
      actual PDF, visually/structurally verify layout, extract the text
      layer the way an ATS parser would and verify contact info survives
      and keyword coverage is real, apply relevance-weighted cutting if it
      overflows a page limit. The biggest standalone piece of new work in
      this phase — plan its own sub-chunks when we get there.

## Open questions

- Exact scoring formula for job-posting normalization (chunk 2) — not
  decided yet, needs its own design pass once we're there.
- Whether the circuit breaker's state lives in Redis from day one or
  starts in-process and gets promoted later — leaning Redis-from-the-start
  given the rate limiter already established "shared state across workers,
  not per-process" as the right default for this codebase.
