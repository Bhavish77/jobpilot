# Phase 6 — Frontend

Roadmap wording: "Next.js chat UI + application-pipeline dashboard
(Discover / Pipeline / Job Workspace, per the UI mockup artifact). Live
updates via the Notify WebSocket. **Ship v0.9.**"

Decision made before planning (user explicitly chose this over reusing the
old mockup): design fresh from the written spec in
`docs/DESIGN_DECISIONS.md` ("UX flow — the model that stuck"), not from the
earlier "JobPilot Screens" artifact.

## Scope correction: what the backend actually supports today

Read every router before planning a single screen, same discipline as
every prior phase — three real gaps turned up:

- **`GET /jobs` is still Phase 1's mock stub.** Three hardcoded fake jobs
  (Anthropic/Scale AI/Vercel), `match_score` a literal constant. Phase 4
  built the real `JobPosting` table and ~424 real ingested rows, but
  nothing ever pointed `/jobs` at it. `JobPosting`'s own docstring already
  calls this out: "no per-user match score here... that's a query-time
  concern (whenever `/jobs` is actually called by a logged-in user), not
  something ingestion can meaningfully compute" — the intent was always
  there, just never wired up. **Fixing this is a prerequisite, not
  optional**: building a real Discover screen against fake data would
  mean the frontend's first real feature renders nothing true.
- **No `GET /applications` list endpoint.** Only
  `GET /applications/{job_posting_id}` (one at a time) exists. Pipeline
  needs every application for the logged-in user, grouped by status, to
  render its four columns at all.
- **No CORS configured on agent-core.** `main.py`'s own comment already
  flagged this ("will need CORS here once it [frontend] exists"). The
  Next.js app runs on a different origin (`:3000` vs `:8000`) and needs
  credentialed (cookie-carrying) cross-origin requests to work at all.

One more judgment call, not a hard gap: Interview Prep's chat has no
history-read endpoint — the checkpointer persists the full message list
server-side, but nothing exposes it. Without it, reopening a Job
Workspace's Interview Prep tab would always start blank even though the
conversation is really still there. Adding a thin read endpoint (same
`aget_state` pattern `/prepare/status` already uses) is cheap and avoids
a real rough edge in exactly the kind of polish this phase is about —
included as a prerequisite chunk, not deferred.

## Design system decisions

- **Stack**: Next.js (App Router, TypeScript) + Tailwind CSS + a small
  `components/ui/` primitive library following the shadcn/ui pattern
  (Radix UI primitives for accessible behavior, `class-variance-authority`
  for variants, Tailwind for styling) — copy-owned component code, not a
  black-box UI kit dependency. This is the closest match to "a UI designer
  built a component system for the whole app": every primitive lives in
  the repo, reads as plain React, and is trivial to restyle globally by
  changing tokens rather than hunting through a third-party library's API.
- **Tokens as CSS variables** (HSL-based, light + dark), the same
  convention shadcn/ui popularized — one place to change `--primary` and
  every component that references it updates, instead of hunting
  hardcoded hex values across components.
- **Color direction**: a deep slate/indigo primary (trustworthy,
  tech-forward — the register this product's audience expects from a
  modern SaaS tool) on a clean, near-white neutral background in light
  mode (near-black slate in dark mode), with a vivid indigo/violet accent
  reserved for primary actions ("Prepare," "Apply") so they're never
  ambiguous. Pipeline's four statuses get their own fixed semantic colors
  (amber=preparing, blue=ready to apply, green=applied, violet=
  interviewing) so the board is scannable by color alone, not just text.
  Every pairing is chosen/checked for WCAG AA contrast — not "looks fine,"
  actually verified against real contrast ratios before anything ships.
- **Typography**: one font family throughout (Inter, via `next/font`, no
  extra network request, no layout shift) and Tailwind's default type
  scale used consistently (`text-sm` body, `text-base` default, `font-
  medium` for labels, `font-semibold`/`font-bold` for headings only) — no
  per-page one-off font sizes.
- **Dark mode**: supported from the start via `next-themes`, since the
  token architecture makes it nearly free once the CSS variables exist —
  not bolted on later.

## Chunks

**Prerequisite backend work:**

- [x] **0a. CORS middleware** on agent-core, `allow_origins=[settings.frontend_url]`,
      `allow_credentials=True` — scoped to the one real frontend origin,
      not `*`, since credentialed requests need a real origin allow-list
      anyway (the browser rejects `*` + credentials together).
      **Verified**: a real `OPTIONS` preflight from `Origin:
      http://localhost:3000` got back `access-control-allow-credentials:
      true` and `access-control-allow-origin: http://localhost:3000`.
- [x] **0b. Real `GET /jobs`** — queries `JobPosting`, paginates, and
      computes a real (simple, deterministic, no LLM call) match score:
      keyword overlap between the user's active resume and each posting's
      title+description. The tokenizer was pulled out of `resume_pdf.py`
      into a new shared `jobpilot_shared/text_matching.py`
      (`extract_keywords`) rather than importing a private `_keywords`
      across modules, since it's now needed by two independent call
      sites. Not a sophisticated ranking model — explicitly scoped to
      "real instead of fake," matching this phase's actual job (frontend),
      not inventing a new ML ranking feature.
      **Verified**: real response against the real ~517-row table (grew
      from Phase 4's ~424 via Celery Beat's daily re-ingestion), each job
      with a distinct, non-hardcoded `match_score` computed against the
      test user's actual resume, `has_resume: true`.
- [x] **0c. `GET /applications`** — lists the logged-in user's
      applications with an outer join against `JobPosting` (by casting its
      UUID `id` to text — `job_posting_id` is a client-chosen opaque
      string, not guaranteed to match a real posting, since plenty of
      earlier test data used made-up ids) for title/company, falling back
      to the raw id when there's no match.
      **Verified**: real response listing every test application with
      correct status/version, falling back to the job_posting_id string
      for old test rows with no matching real `JobPosting`.
- [x] **0d. `GET /interview/{job_posting_id}/history`** — reads the
      interview_graph's checkpointed message list via `aget_state`, same
      pattern `/prepare/status` already established, so a chat tab can
      restore on reopen instead of always starting blank.
      **Verified**: real response for a job with no interview turns yet
      correctly returned `{"messages": []}` rather than erroring.

**Design system + scaffold:**

- [x] **1. Next.js scaffold + design system foundation** — `frontend/`
      initialized (Next.js 15, App Router, TypeScript, Tailwind v4's
      CSS-first `@theme` config), `next-themes` wired for dark mode, Inter
      via `next/font`, and the first primitives (Button, Input, Card,
      Badge, Avatar, Spinner) built shadcn/ui-style: Radix primitives +
      `class-variance-authority` + Tailwind, owned as plain component
      code in `components/ui/`, not a black-box dependency.

      **Every color pairing computed against the real WCAG 2.1 contrast
      formula, not eyeballed** (`node` script run directly) — two real
      findings this caught before any screen was built on top of them:
      (1) white text on the dark-mode primary/accent/destructive colors
      only hit ~2.9-3:1, under even the 3:1 large-text minimum — fixed by
      using dark slate text on those lighter dark-mode colors instead
      (passes at ~6-6.6:1); light mode's deeper colors keep white text
      fine (5.7-6.3:1). (2) A light `slate-300` border for input fields
      only hit 1.4:1, nowhere near the 3:1 WCAG 1.4.11 wants for an
      interactive component's own boundary — split into two tokens,
      `--border` (decorative, cards/dividers, can stay subtle) and
      `--input` (darker, 4.55:1 light / 3.75:1 dark, for real field
      boundaries). Every other pairing — body text, muted text, the four
      Pipeline status badges in both themes — checked at 4.5:1+ (most
      landed 6-10.6:1).

      **Verified for real**: `npm run build` compiled clean with zero
      TypeScript/lint errors; `npm run dev` served both `/` and
      `/style-guide` at real `200`s (not just "it built"); fetched the
      actual compiled CSS and confirmed both the light (`:root`) and dark
      (`.dark`) token values are genuinely present (e.g. two distinct
      `--primary` declarations, `#4f46e5` and `#818cf8`), not just
      written in source and silently dropped by the build.

      **Dev-server note**: port 3000 was already occupied by an unrelated
      pre-existing process on this machine (confirmed via `netstat`/
      `Get-Process` — a different Node process, nothing to do with this
      project) — left untouched rather than killed; Next.js auto-fell-back
      to port 3001, used for all verification above. `FRONTEND_URL`/CORS
      config will need to point at whichever port the frontend actually
      runs on once this matters for real cross-origin testing (chunk 3+).

**Screens:**

- [x] **2. Landing page** (public, unauthenticated) — hero, the four real
      value props (smart matching, tailored resume/cover letter, interview
      prep, "you're always in control" — the prepare-only guarantee stated
      as a selling point, not buried in fine print), sign-up/log-in CTAs,
      dark-mode toggle in the header. **Verified**: clean build, real
      dev-server response confirmed every section's actual copy renders.
- [x] **3. Auth pages** — `/login` and `/register` (separate routes, not
      query-param toggled — clearer URLs), both wired to the real
      `/auth/*` endpoints plus a real "Continue with Google" link (a plain
      `<a>` full-page navigation, not a fetch — OAuth needs a real browser
      redirect). `lib/api.ts` is the typed fetch wrapper every screen uses
      from here on (`credentials: "include"` on every call — the session
      is an httpOnly cookie, never a token this code could read itself).
      `SessionProvider` wraps the whole app in the root layout, doing one
      `/auth/me` call on load and sharing the result via context instead
      of every screen independently re-fetching "who's logged in."

      **Real port mismatch found and fixed while testing**: the dev
      server runs on :3001 (chunk 1's port-3000 collision with an
      unrelated process), but `FRONTEND_URL`/CORS was still configured
      for :3000 — any real browser request would have failed CORS
      silently. Updated the local `.env`'s `FRONTEND_URL` to match and
      restarted agent-core.
      **Verified for real** (not mockable — this is the actual CORS +
      cookie handshake): registered a brand-new user with `Origin:
      http://localhost:3001` and got back a real `Set-Cookie` plus
      `access-control-allow-origin: http://localhost:3001`; the same
      cookie + Origin then worked against `/auth/me`. Both `/login` and
      `/register` render cleanly with no runtime errors (real `200`s from
      the dev server, actual form content confirmed in the response).
- [x] **4. App shell** — `app/(app)/layout.tsx`, a route group so every
      screen under it (Discover/Pipeline/Profile/Job Workspace) gets the
      sidebar + auth gate just by existing inside `(app)/`, with no
      per-page boilerplate. Not logged in -> redirected to `/login`
      (checked against the real `SessionProvider`, not a guess); still
      loading -> a spinner, never a flash of protected content.
      **Verified**: real dev-server request with no session cookie
      returned the gated loading state (spinner markup present, no
      protected content leaked), not a crash or the real page content.
- [x] **5. Discover** — ranked job list against chunk 0b's real
      `/jobs` data, a "keyword match" badge (deliberately labeled, not a
      bare percentage — a real ~5-9% keyword-overlap score reads as
      broken if presented as an unqualified "match," but is an honest,
      useful relative signal once labeled for what it actually is),
      expandable inline JD, checkbox multi-select, per-card and bulk
      "Prepare" actions wired to the real `POST /prepare`. A banner
      prompts for a resume upload when `has_resume` is false, since match
      scores need one to mean anything.
      **Verified**: clean build; real dev-server smoke test confirmed no
      runtime error.
- [x] **6. Pipeline** — board with the four real status columns (chunk
      0c's data), cards linking into the Job Workspace at
      `/pipeline/[jobPostingId]`.
- [x] **7. Job Workspace** — overview header (title/company/status) + the
      three tabs: Resume, Cover Letter, Interview Prep (chat, using chunk
      0d's history endpoint), plus the accept/reject UI for a pending
      review and a "Mark as applied" action wired to chunk 0c's
      optimistic-locking endpoint.

      **A real bug found and fixed while verifying these two chunks
      end-to-end** (not a frontend bug — a backend bug this real test
      happened to surface): a fresh `/prepare` run crashed mid-pipeline
      with `RuntimeError: Event loop is closed` inside `redis.asyncio`'s
      disconnect path, during `generate_curriculum`. Same root cause as
      Phase 4 chunk 4's Postgres bug, different shared resource:
      `redis_client.py`'s connection pool (`_pool`) is also created once
      at import time and binds to whichever event loop touches it first.
      `dispose_engine()` (chunk 4) only ever disposed the SQLAlchemy
      engine — nothing disposed the Redis pool, and `job_tasks.py`'s
      circuit breaker + `prepare_tasks.py`'s rate limiter/`publish_event`
      both touch it, so any job-worker process that ran more than one
      Redis-touching task was always going to hit this eventually. Fixed
      with the identical pattern: a new `dispose_pool()` in
      `redis_client.py`, called in the same `try/finally` as
      `dispose_engine()` in both `prepare_tasks.py` and `job_tasks.py`.

      **Verified for real, full chain, end-to-end** (Gemini's quota had
      reset by this point — confirmed by this very run succeeding):
      registered a real new user, uploaded a real resume, called the real
      `/jobs` endpoint and took its top match, ran `/prepare` through all
      four real LLM calls to `pending_review`, approved it
      (`resume_finalized`, `page_fit: true`), confirmed `GET
      /applications` correctly showed `ready_to_apply` with the right
      title/company joined in, and confirmed `/interview/turn` +
      `/interview/.../history` return exactly the shapes the new
      `InterviewChat` component expects (`{reply}` and `{messages:
      [{role, content}]}`). Every data contract the Pipeline and Job
      Workspace pages depend on is now proven against real responses, not
      assumed from reading the router code.
- [x] **8. Profile** — account info (name/email/Google-linked),
      resume upload matching what `POST /resumes` actually accepts
      (paste/plain-text, not a PDF parser — that's not what the backend
      takes), GitHub connect button (`/auth/github/connect`), showing the
      linked username once connected.
      **Verified**: clean build; a stale `.next` dev cache (from running
      `npm run build` while the dev server was still live against the
      same output directory) caused a transient `500` on every route, not
      specific to this page — cleared the cache and restarted the dev
      server fresh, after which all seven routes (`/`, `/login`,
      `/register`, `/discover`, `/pipeline`, `/profile`, `/style-guide`)
      returned real `200`s.
- [x] **9. Live updates** — `NotifyListener` (mounted once in the root
      layout, alongside a small hand-rolled `ToastProvider` — one use
      case, not worth a new dependency) opens a WebSocket to Notify as
      soon as a real session exists; the browser sends the same
      `jobpilot_session` cookie on the upgrade automatically (proven for
      real in Phase 5). On `type: "tailoring_ready"` it surfaces a toast
      and dispatches a `window` custom event the Pipeline page listens
      for to refetch — live update without a global state manager.
      Reconnects on an unexpected close while still logged in, so a
      dropped connection doesn't silently mean missing every push for the
      rest of the session.
      **Verified for real**: triggered an actual `publish_event()` call
      for the real test user from inside the `job-worker` image while a
      real authenticated WebSocket client (the same approach Phase 5
      used) listened on the real `notify` container — confirmed the
      exact message shape (`{"userId", "type": "tailoring_ready",
      "payload"}`) the frontend's `data.type === "tailoring_ready"` check
      depends on arrives correctly over the wire.

## Phase 6 complete

All chunks (0a-0d, 1-9) shipped and verified against the real running
stack — not just built, but exercised through actual HTTP/WebSocket
calls against live Postgres/Redis/Mongo/RabbitMQ, including one real
full LLM pipeline run (`/prepare` -> 4 real Gemini calls ->
`pending_review` -> `/approve` -> `resume_finalized`) and a real bug
found and fixed along the way (the Redis connection-pool disposal bug,
chunk 6/7's writeup above).

## Post-ship polish pass (user feedback after first real use)

Four real issues/requests from actually using the app, not planned
chunks — fixed the same day, same verification discipline:

- **Real layout bug**: `app/(app)/layout.tsx`'s shell used `min-h-screen`
  on the flex container instead of `h-screen overflow-hidden`. The
  sidebar has no `sticky`/`fixed` positioning, so once a page's content
  overflowed the viewport, the *whole page* scrolled — sidebar included —
  instead of only `main`'s own `overflow-y-auto` region scrolling.
  Visible in a real screenshot: scrolled down on Discover, the sidebar
  had scrolled away entirely, leaving a blank gutter. Fixed by making the
  shell itself `h-screen overflow-hidden` so the page can never scroll,
  only `main` can — the standard fixed-sidebar app-shell pattern.
- **PDF resume upload.** Added `POST /resumes/extract-pdf` — reuses
  PyMuPDF (already a backend dependency for the ATS text-layer check,
  `resume_pdf.py`) rather than adding a client-side PDF parser.
  Deliberately extraction-only, no DB write: returns the extracted text
  for the Profile page's textarea so the user reviews/edits before the
  existing `POST /resumes` actually saves it — PDF extraction is good,
  not perfect (columns/tables/unusual fonts can come out garbled), so
  nothing is saved blind. **Verified for real**: generated a real PDF
  with `compile_resume_pdf`, uploaded it through the real endpoint,
  confirmed the exact text round-tripped back out correctly.
- **An actually-engaging progress UI**, replacing the single static
  "Preparing" badge the Job Workspace previously showed (a wall of blank
  space otherwise). `GET /prepare/.../status` now returns a real `steps`
  array computed directly off the same checkpointed state fields
  `prepare_graph.py`'s own routing already reads — never a fake
  fixed-duration progress bar, it's physically impossible for a step to
  show "done" before the graph actually finished it. `PrepareProgress`
  (new component) renders this as an animated vertical stepper (pulsing
  ring on the active step, a connecting line that fills in as steps
  complete, ambient rotating flavor text) and the Job Workspace polls
  `/status` every 3s while the pipeline is actually running, stopping
  itself the moment it isn't. **Verified live against a real fresh
  `/prepare` run**, polling the real endpoint end to end: watched
  `quality_check` finish alone, then `resume`+`curriculum` (confirming
  the parallel branch really is tracked independently — curriculum
  finished before `cover_letter` even started), then `cover_letter`,
  landing at `pending_review` with 5/6 done and only `finalize`
  remaining — which then flipped to done immediately after `/approve`.
  Every transition matched the real graph's actual execution order.
- **General visual polish**: color-coded Discover's match badge (reuses
  the Pipeline status palette as a quick scannable "worth a look" signal
  rather than every card looking identical regardless of score), hover
  elevation on Discover cards (previously only Pipeline cards had it),
  and a back-to-Pipeline link on the Job Workspace (there was previously
  no way back except the sidebar).

## Real production bug found via actual use (not planned, not staged)

The user ran a real pipeline through the real UI and asked why it had
been stuck for hours. Investigation (not a guess — read the real
`job-worker` logs for the real timestamp) found a genuine gap:
`task_acks_late=True` only protects against the *worker process* dying
mid-task; an ordinary exception raised *inside* a healthy task (here, a
transient `GoogleAPIError` 503 "high demand, try again later" during
`draft_cover_letter`) just kills that task permanently — no redelivery,
no retry, nothing. The checkpoint sat at 3/6 steps forever, and
`/prepare/status` had no way to tell "still genuinely running" apart
from "ran once, died, will never run again," since both look identical
from the checkpoint alone (`snapshot.next` still points at the unfinished
node either way).

**Fixed in two parts:**

1. **`prepare_tasks.py`**: Celery `autoretry_for=(GoogleAPIError,)` with
   exponential backoff (`retry_backoff_max=300`, `max_retries=5`).
   Deliberately scoped to that one exception class, not blanket
   `Exception` — confirmed via `issubclass()` that `GoogleRateLimitError`
   (sustained quota exhaustion, can last ~24h) is a *sibling* class, not
   a subclass, so a real quota lockout correctly does NOT get caught and
   retried pointlessly; only genuinely transient server errors do.
2. **Surfacing real failure to the user**, since auto-retry alone doesn't
   cover quota lockouts and "silently stuck forever" was the actual
   complaint: new migration `c3d4e5f6a7b8` adds
   `Application.last_prepare_task_id`, set on every `POST /prepare`.
   `GET /prepare/status` now checks that task's *real* Celery result
   state via the result backend whenever the checkpoint alone would say
   "in_progress" — a genuine `FAILURE` returns a new `"failed"` status
   with a friendly message instead of pretending nothing's wrong. For a
   rate-limit failure specifically, Gemini's own error already states
   the reset time, so it's parsed out and shown directly ("try again in
   about 11h 42m") rather than a generic "try again later." The Job
   Workspace renders this as a destructive-styled card with a **Retry**
   button — which, thanks to chunk 1's resumable routing, re-enters at
   whatever step actually failed, not from scratch.

   Small related cleanup: `POST /prepare`'s `job_description` is now
   optional — the backend looks it up from the real `JobPosting` row by
   id when omitted, so the Retry button (and any future caller that only
   has the id) doesn't need to carry the full description text around.

**Verified for real, twice over** — first on the user's actual stuck
application (manually re-queued it live, watched it correctly skip the
three already-completed steps and resume at review, confirming the
*routing* half works), then on the *detection* half: since Gemini's
quota was, by coincidence, genuinely exhausted at the time, a fresh real
`/prepare` call reliably reproduced a real failure end-to-end —
`/status` correctly returned `{"status": "failed", "error": "The AI
provider's free-tier limit was reached — try again in about 11h 42m."}`
instead of hanging as `"in_progress"` forever. Both halves proven against
real Celery task state, not mocked.

## Finishing the rate limiter for real (user question: "don't we already have this?")

Sharp catch mid-session: we *do* have `acquire_llm_permit()`, so why was
a rate-limit error even possible? Answer, traced through precisely:

- **The RPM bucket was always a stub.** Its own docstring said so since
  Phase 1: the atomic acquire (check-and-decrement, race-proof via Lua)
  was real, but nothing ever refilled it — the counter only ever went
  down. In practice this meant "N calls ever, across the app's whole
  lifetime," not "N calls per minute."
- **Even finished, RPM was never going to stop today's actual failure.**
  The real error was `GenerateRequestsPerDayPerProjectPerModel-FreeTier,
  limit: 20` — a **daily** cap, a completely different axis from RPM.
  Nothing in the codebase modeled a per-day budget at all, so there was
  zero local protection against the one constraint that kept actually
  biting us; it was only ever discovered via the provider's own 429,
  often mid-pipeline after other steps had already succeeded.

**Built both for real:**

- `acquire_llm_permit` rewritten with a genuine lazy-refill token bucket
  — one atomic Lua script computes elapsed time via Redis's own `TIME`
  command (not a client timestamp, since agent-core + 12 job-worker
  processes would each bring a slightly different clock to the same
  shared bucket), refills proportionally, caps at capacity, grants/denies
  in the same atomic step.
- `acquire_daily_quota` — a separate `llm:daily_quota:{UTC date}` Redis
  key, atomic `INCR`, gated at `LLM_DAILY_QUOTA` (20, matching the real
  free-tier cap), self-resetting daily via the date-scoped key + a ~25h
  safety TTL. Explicitly documented as a *best-effort local mirror*, not
  authoritative — the real error reported an odd offset ("11h42m," not a
  clean midnight-UTC reset), so perfect alignment isn't guaranteed, only
  a much closer approximation than having no local tracking at all.
- `call_llm()` checks RPM first, daily quota second, deliberately in that
  order — RPM tokens refill on their own, so "wasting" one on a call the
  daily cap then blocks is cheap; a daily-quota slot is irreplaceable
  until tomorrow, so it's only spent once the call is otherwise actually
  about to happen.
- `/status`'s `_friendly_task_error` extended to recognize our own
  `RateLimitExceeded` messages directly (already clean, shown verbatim)
  alongside the provider's raw error text (still parsed for the
  retry-after duration).

**A real regression found and fixed before any of this shipped**: the
very first real test against the live Redis instance failed with
`WRONGTYPE Operation against a key holding the wrong kind of value`. The
production `llm:rate_limit:tokens` key still held a plain Redis *string*
from the old stub's `DECR`-based implementation; the new script does
`HGET`/`HSET` (a hash) against the same key name, and Redis enforces one
data type per key. Changing a key's underlying structure silently breaks
on next use unless the old key is cleared first — fixed by deleting the
stale key (safe; it's a rate-limiter cache key, not user data, and
reinitializes cleanly on the next call since the script already treats a
missing key as "start full").

**Verified three ways, no real LLM calls needed for the first two** (the
expensive/rate-limited resource is the provider, not Redis — mock-first
discipline applied to infra, not just LLM calls):
1. Direct Lua-script test with small numbers (capacity 3, refill 1
   token/sec): drained exactly 3 grants then correctly denied 2 more;
   after a 2.5s wait, granted exactly 2 more (proving real elapsed-time
   refill math, not a guess).
2. Direct daily-quota test: calls 1-20 correctly `within_limit=True`,
   21-22 correctly `False`.
3. **Real end-to-end, on the exact application that prompted this
   investigation**: re-triggered it through the equivalent of the real
   `/prepare` path (this time correctly recording `last_prepare_task_id`,
   unlike the first manual retry earlier in the session). Confirmed
   directly against the checkpoint + Celery result backend — the exact
   same read `/status` performs — that it now resolves to `{"status":
   "failed", ...}` instead of silently hanging, for the real user's real
   stuck job.

**One honest limitation surfaced by this same real test**: a brand-new
daily-quota counter can't retroactively know about calls made *before*
it existed — it let one more real call through to Gemini today (correctly
rejected by the provider), since from the counter's own fresh perspective
today's budget wasn't spent yet. Manually aligned the counter with
reality for the remainder of today (`SET` to the limit) to stop burning
further real attempts; from tomorrow's fresh UTC day onward it starts in
sync and will correctly fast-fail locally, with no round trip to the
provider needed.
