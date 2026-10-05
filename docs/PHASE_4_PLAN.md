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
- [x] **2. Job model + ingestion task** — `JobPosting` table (new
      migration `b2c3d4e5f6a7`) + `shared/jobpilot_shared/job_sources.py`
      (fetchers + normalizers for RemoteOK and Arbeitnow — confirmed their
      real response shapes via curl before writing any code, same
      discipline as the Gemini/LangGraph surprises) +
      `shared/jobpilot_shared/job_tasks.py` (the Celery task). Adzuna
      deferred — needs app_id/app_key credentials nobody's signed up for,
      same category of deferral as GitHub ingestion in Phase 3. No
      per-user match score at ingestion (see "Scope correction" note
      above the chunks) — raw ingestion doesn't know which user it's for.
      Added a real Celery Beat container (`job-worker-beat` in
      `docker-compose.yml`) — the schedule alone was configuration with
      nothing running it.
      **Verified in three layers, mocks first per your instruction**:
      (1) hand-built fake data matching the real API shapes, to test
      `normalize_remoteok`/`normalize_arbeitnow` (caught a real bug this
      way — consecutive HTML tags collapsed into double spaces — fixed
      before any real call); (2) mock data again to test the actual
      storage side (`store_raw_postings` + `upsert_job_postings` against
      real Mongo/Postgres) — ran it twice with the same ids and confirmed
      exactly 2 rows, not 4, proving upsert doesn't duplicate; (3) *one*
      real end-to-end run, calling the actual function directly
      (99 RemoteOK + 325 Arbeitnow postings, real companies/titles, Mongo
      raw count exactly matching Postgres's 424), then *one* more through
      the real Celery dispatch path (`.delay()` → RabbitMQ → job-worker
      picked it up → succeeded with identical counts, confirming the
      upsert behavior holds through the real queue too, not just when
      called directly). Left the real ingested data in place — it's
      legitimate seed data, not throwaway test data.
- [x] **3. Circuit breaker + retry/backoff/jitter + timeout** around the
      RemoteOK/Arbeitnow calls. `tenacity` handles retry/backoff/jitter
      (`wait_random_exponential`, 3 attempts) and only retries errors a
      retry could plausibly fix — `httpx.TransportError` (timeouts,
      connection failures) or a 5xx `HTTPStatusError`, never 4xx, since
      retrying a malformed request just reproduces the same 4xx. A new
      hand-rolled `shared/jobpilot_shared/circuit_breaker.py` wraps
      *outside* the retried call, at a coarser grain — Redis-backed (not
      in-process) for the same reason as the rate limiter (`job-worker`
      forks into 12 processes; in-process state would be blind to
      failures in the other 11). Deliberately **not** using the rate
      limiter's atomic Lua-script pattern here — failures accumulate one
      at a time during an occasional ingestion run, far lower concurrency
      and lower stakes than the rate limiter's race, so plain Redis ops
      are an appropriately-sized mechanism rather than copying the
      heavier pattern by default.
      **Verified with mocks first**: a fake always-failing function
      proved the circuit opens after 3 consecutive failures and then
      fails fast *without even calling the function* on the 4th attempt
      (call count stayed at 3, not 4); a second test with a 2-second
      cooldown proved it stays open immediately after tripping, allows a
      trial call through once the cooldown expires, and a success resets
      the failure count to 0. The retry policy itself was tested directly
      against fake exceptions: a simulated timeout retried twice then
      succeeded on attempt 3; a simulated 404 was correctly *not*
      retried (1 attempt, not 3). Only after all of that passed: one real
      run of the actual ingestion task, same 99+325 results as chunk 2,
      confirming the new wrapping didn't break the real integration —
      and confirmed both real sources' circuit state is clean (0
      failures, no leftover test keys).
- [x] **4. Wrap `prepare_graph` in one real Celery task** — per the
      earlier design-doc revision (`docs/DESIGN_DECISIONS.md`, "Why
      background jobs need a queue"): one task invokes the whole graph,
      not four tasks coordinated by Celery's own chain/group/chord.
      `/prepare` changes from `await`ing the graph directly to
      `.delay()`-ing this task and returning immediately; `/status` reads
      the same checkpointed state back out via agent-core's own
      already-compiled `prepare_graph` (no separate task-result
      tracking needed — the checkpointer already has everything);
      `/approve` stays synchronous since resuming after the interrupt is
      cheap. Depends on chunk 1 — without resumable routing, Celery's
      `task_acks_late` redelivery-on-crash would hit the exact
      wasted-work problem just found.

      **Prerequisite refactor, not anticipated when this chunk was
      planned**: `job-worker`'s Docker image never copied
      `agent-core/app/`, so the Celery task had no access to any
      LangGraph code at all. Moved the entire `graph/` package from
      `agent-core/app/graph/` to `shared/jobpilot_shared/graph/` (`git
      mv`, 11 files, imports repointed `app.graph` ->
      `jobpilot_shared.graph`) per the "same codebase, two deploy
      targets" standing rule — this is exactly the kind of logic that
      belongs in `shared/`, not duplicated or newly-exposed only to one
      service. Moved the LangGraph/LangChain dependencies from
      `agent-core/requirements.txt` to `shared/pyproject.toml` to match.
      Verified zero behavior change after the move: `/health` and
      `/ready` both passed, one real `/chat` call still worked.

      **Real bug found by the first live end-to-end test, not by
      inspection**: `/prepare` hung at `{"status":"not_started"}` for the
      full 2-minute poll. `job-worker` logs showed `RuntimeError: Task
      ... got Future ... attached to a different loop`. Root cause:
      `shared/jobpilot_shared/db.py`'s async engine/session factory is
      created once at import time, and its connection pool binds to
      whichever event loop first touches it. That's safe for
      `agent-core` (uvicorn keeps one event loop alive for the process's
      entire life) but not for Celery tasks — each task body is
      `asyncio.run(...)`, which spins up and tears down its *own* event
      loop every call, so a connection left in the pool from one task's
      loop breaks the next task that reuses it. (An earlier test calling
      `ingest_jobs.delay()` twice against the same worker had appeared to
      survive this — correctly flagged at the time as possibly luck
      rather than proof, which this bug confirmed.)
      **Fix**: added `dispose_engine()` to `db.py` (`await
      engine.dispose()`), called via `try/finally` at the end of both
      `ingest_jobs` (`job_tasks.py`) and `run_prepare_pipeline`
      (`prepare_tasks.py`)'s task bodies, right before each one's
      `asyncio.run()` loop closes — forces the next task's fresh loop to
      open fresh connections instead of reusing stale ones.
      **Verified for real** (end-to-end, the standing "real call
      sparingly, as the final check" instruction — mocking isn't
      meaningful here since the whole bug *is* the real Celery+Postgres+
      asyncio interaction): rebuilt `agent-core`/`job-worker`, re-ran
      `/prepare` against a user with a real substantial resume. Worker
      logs showed four real Gemini calls (resume -> cover letter ->
      interview-prep -> review) with no loop error, task succeeded in
      ~32s with `{'status': 'pending_review'}`; `/status` reflected
      `pending_review` with the full review payload; `/approve` with
      `{"decision":"accept"}` returned `reviewed_accepted` with
      `resume_output`, `cover_letter_output`, and `curriculum` all
      populated. Full round trip confirmed, including the fix holding
      under the actual failure mode that broke it the first time.
- [x] **5. Optimistic-locking "apply to job" endpoint** — `Application`
      already has the `version` column (Phase 1). New
      `agent-core/app/routers/applications.py`: `GET
      /applications/{job_posting_id}` (so the client has a version to send
      back, same "never let a client guess at state it should be reading"
      reasoning as the checkpointer) and `POST
      /applications/{job_posting_id}/apply` — validates the status
      precondition (only `ready_to_apply -> applied`, 400 otherwise), then
      `UPDATE ... WHERE id = :id AND version = :version` and checks
      `rowcount`; 0 rows means another request already moved this row,
      rejected as stale (409). Prepare-only/no-auto-submit still holds —
      this never talks to a job board, it only records that the human
      already applied themselves elsewhere.

      **Prerequisite gap found while building this**: `Application.status`
      never actually left `PREPARING` — chunk 4's task body persisted
      `resume_output`/`cover_letter_output`/`interview_curriculum` but
      never flipped status, even though the design doc's "Why background
      jobs need a queue" section explicitly says the task's own body
      "does what `mark_ready_to_apply` was meant to do." Fixed in both
      places that can reach a terminal state: `prepare_tasks.py`'s direct-
      completion path (reached when `review_and_revise` has nothing to
      propose, so `await_review_approval` never interrupts) and
      `agent-core/app/routers/prepare.py`'s `/approve` (reached after a
      real interrupt, for *both* "accept" and "reject" — reject just means
      the originals stand, not that anything failed, so it's still ready
      to apply). Also deleted `shared/jobpilot_shared/tasks.py` — the
      original Phase-1 stub (`generate_resume`/`generate_cover_letter`/
      `generate_interview_prep`/`mark_ready_to_apply` placeholders
      coordinated via Celery `chain`/`group`/`chord`) the design doc
      already flagged as needing replacement once Phase 4 started;
      `prepare_tasks.py` fully supersedes it, so the old stub was dead code
      actively misrepresenting how the pipeline is wired. Removed from
      `celery_app.py`'s `include` list and `worker.py`'s import.

      **Verified**: the status-flip fix needed a real `/prepare ->
      /approve` cycle to prove (it's new behavior in that exact path, not
      something mockable without faking the whole graph) — ran one more
      real end-to-end cycle (new job id, same test user/resume), confirmed
      `GET /applications/{id}` returned `{"status": "ready_to_apply",
      "version": 1}` right after `/approve`, where it previously would
      have stayed `"preparing"`. Then the apply endpoint itself: `POST
      .../apply` with the correct version succeeded (`200`,
      `status=applied`, `version=2`); retrying with the same version
      afterward correctly failed (`400`, since status had already moved
      past `ready_to_apply` — the precondition check alone was enough to
      catch it in this timing); firing two concurrent `apply` calls with
      the same stale version against a `ready_to_apply` row landed one
      `200` and one `400`, with the row ending at exactly `version=2` —
      no double-write regardless of which check caught the second request.
      To confirm the `409` branch's actual mechanism (the race window
      where both requests pass the status precondition and only the
      `UPDATE ... WHERE version=` guard can still catch it) independent of
      HTTP-level timing, ran the identical `UPDATE ... WHERE id=... AND
      version=1` SQL twice directly against Postgres: first affected 1
      row, second affected 0 — proving the exact guard the endpoint's
      `rowcount == 0 -> 409` check depends on is real, not a no-op.
      `GET /applications/does-not-exist` correctly returned `404`.
- [x] **6. ATS/PDF verification loop** — borrowed from `ai-job-search` (see
      `docs/DESIGN_DECISIONS.md`): compile the generated resume to an
      actual PDF, verify it structurally (page overflow) and the way an
      ATS parser would (real text layer, contact info, keyword coverage),
      apply relevance-weighted cutting if it overflows a page limit.

      **Scope correction made before building**: no new persistent
      storage for the compiled PDF. S3 isn't available until Phase 7
      (CLAUDE.md), and the PDF is a pure, deterministic function of
      already-persisted `resume_output` text — the loop's real job is to
      *verify and, if needed, edit `resume_output` itself* until the text
      it leaves behind is confirmed to render as one clean, ATS-parseable
      page. Rendering a PDF again later (e.g. a download button) is just
      re-running the same deterministic render on demand — no blob
      storage decision needed this phase.

      - **6a. WeasyPrint feasibility spike** — the one real install-time
        risk in this phase (every other dependency so far was pure-pip;
        this needs native `libpango`/`libcairo`/`libgdk-pixbuf` system
        packages). First attempt used Debian package names from an older
        release and failed (`libgdk-pixbuf2.0-0` doesn't exist on this
        image's `trixie` base — `apt-cache search` found the real current
        name, `libgdk-pixbuf-2.0-0`). Added the corrected `apt-get` block
        to **both** `job-worker/Dockerfile` and `agent-core/Dockerfile` —
        agent-core needs it too, since `main.py`'s lifespan imports
        `prepare_graph` (and therefore the new node) at startup even
        though job-worker is the only service that ever executes it.
        **Verified**: rebuilt both images clean; a direct script run
        inside the real `job-worker` container rendered a trivial
        HTML resume to PDF with WeasyPrint and read it back with
        PyMuPDF (`import pymupdf`, not the deprecated `fitz` alias),
        confirming page count and extracted text both came back correct
        before anything else was built on top of it.
      - **6b. `shared/jobpilot_shared/resume_pdf.py`: `compile_resume_pdf`**
        — a fixed one-page `@page`-sized HTML/CSS template; the Resume
        Agent's markdown-ish output (`**HEADER**` on its own line,
        `*   **label:** text` bullets) is parsed with the real `markdown`
        library rather than a hand-rolled parser, and one CSS selector
        (`p > strong:only-child`) distinguishes a whole-line bold section
        header from an inline-bold bullet label — both parse to identical
        `<strong>` tags, so the distinction has to be made in CSS, not
        the parser. **Verified** with a hand-built resume string matching
        the real agent's actual output shape: compiled to a valid 1-page
        PDF, contact line/headers/bullet content all present in the
        extracted text.
      - **6c/6d. `check_page_overflow` + `verify_ats_text`** — page count
        is a direct signal here (not inferred) since `@page` already
        fixed a real page size; WeasyPrint's own layout decision is just
        read back out. ATS verification is pattern-based (a general
        email/phone-shaped regex), not matched against one known-correct
        value like `User.email` — a candidate's resume frequently lists a
        different email than their JobPilot login, so asserting equality
        to the account email would fail perfectly good resumes. **Bug
        found during mock verification, fixed before any real call**: the
        keyword-overlap regex allowed trailing sentence punctuation into
        a token (`"experience."` as one token, distinct from
        `"experience"`), which happened to still match in the first test
        only because the job description and resume text both broke
        sentences at the same word — fixed by stripping trailing
        `.,;:!?` off every extracted token. **Verified** with three mock
        cases: a good resume (1 page, contact info found, 0.75 keyword
        coverage), a deliberately bloated one (correctly detected as 3
        pages, `overflow: True`), and one with no contact info at all
        (correctly `email_found`/`phone_found: False`).
      - **6e. `cut_lowest_relevance_line` + `fit_resume_to_page`** — only
        bullet lines are ever cut (headers/summary/contact info are
        untouched regardless of how constrained this gets); each bullet
        is scored by JD keyword overlap (full weight) plus overlap with
        `cover_letter_output` (half weight, since losing a line the cover
        letter depends on would make the two documents inconsistent —
        worth something, not as much as matching the actual job ask).
        Bounded by `max_attempts` rather than looping until it fits, since
        a resume that's already over the limit with zero bullets left to
        cut can't be fixed this way and must still return. **Verified**:
        built a resume with one highly JD-relevant bullet and 30 generic
        filler bullets (overflowed to 2 pages); the loop converged to 1
        page in 11 attempts, keeping the relevant bullet and cutting 11
        of the 30 irrelevant ones.
      - **6f. Wired into `prepare_graph`** as a real node,
        `compile_and_fit_resume`, between `await_review_approval` and
        `END` — reached on both the interrupt-resume path (`/approve`)
        and the direct-completion path (`review_and_revise` had nothing
        to propose, so `await_review_approval` never interrupted), since
        it's a plain edge off a node both paths already pass through.
        `_route_after_quality_check` got a second done-set
        (`_RESUME_BRANCH_REVIEW_DONE_STATUSES` vs.
        `_RESUME_BRANCH_FULLY_DONE_STATUSES`) so a retry after review has
        resolved but before the PDF step has run routes straight to
        `compile_and_fit_resume` instead of re-triggering a decision
        that's already been made — same resumable-routing discipline as
        chunk 1, extended to cover the new terminal step. `pdf_check`
        added to `PrepareState` and surfaced through `/status`/`/approve`
        via `prepare.py`'s `_result_payload`.
        **Verified for real, end-to-end** (the standing "sparingly, as
        the final check" instruction — this step is deterministic, but
        it's now a load-bearing part of the real graph, worth one real
        pass): ran a fresh `/prepare` -> real LLM calls -> `pending_review`
        -> `/approve`. Response came back `"status": "resume_finalized"`
        with a real `pdf_check`: `page_fit: true`, `cut_attempts: 0`
        (fit cleanly, no cutting needed), `keyword_coverage: 0.85`, and —
        correctly — `email_found`/`phone_found: false`, because this test
        fixture's actual resume content contains literal
        `[Email Address]`/`[Phone Number]` placeholders rather than real
        contact info. Confirms the check is doing real work, not just
        returning a fixed shape: it correctly flagged a resume that would
        genuinely fail ATS parsing in its current form.

## Open questions

- Exact scoring formula for job-posting normalization (chunk 2) — not
  decided yet, needs its own design pass once we're there.
- Whether the circuit breaker's state lives in Redis from day one or
  starts in-process and gets promoted later — leaning Redis-from-the-start
  given the rate limiter already established "shared state across workers,
  not per-process" as the right default for this codebase.
