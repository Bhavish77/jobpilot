# Phase 5 — Notify: Node.js WebSocket service

Roadmap wording: "WebSocket server per logged-in user; subscribe to Redis
pub/sub events from Agent Core / Job Worker (the skeleton for this already
exists in `notify/index.js`). Push 'new match,' 'tailoring ready,'
'interview reminder'; log events to MongoDB. Deliberately profile one
blocking sync call freezing every other connection, then fix it."

## What already exists (Phase 0 skeleton, re-checked before planning)

`notify/index.js` already has the real shape: Express + `ws` WebSocket
server, per-user connection tracking (`Map<userId, Set<WebSocket>>`), a
dedicated `ioredis` subscriber on `jobpilot:events`, and a `pushToUser`
dispatcher. `/health` and `/ready` exist. What's explicitly marked
not-yet-real in its own comments: the userId comes from a `?userId=` query
param instead of real auth, and nothing anywhere actually publishes to
`jobpilot:events` yet — the whole pipeline is wired but nothing is plugged
into either end of it.

## Scope correction: which events are actually real right now

Traced each named event against what the system can actually produce
today, same discipline as every prior phase's roadmap-wording check:

- **"Tailoring ready" is real.** Phase 4 (chunks 4/5) already built the
  exact moment this fires: `Application.status` flips to `READY_TO_APPLY`
  in two places (`prepare_tasks.py`'s direct-completion path,
  `prepare.py`'s `/approve`). This phase just needs to publish an event at
  that same point.
- **"New match" is not buildable yet.** It implies a per-user relevance
  score tying a newly-ingested job posting to a specific user's profile.
  Phase 4 chunk 2 explicitly deferred exactly this ("no per-user match
  score at ingestion — raw ingestion doesn't know which user it's for").
  Building notification plumbing for an event that nothing can ever fire
  would be fake infrastructure. Deferred until job-matching/scoring is a
  real feature (not scoped to any phase yet).
- **"Interview reminder" is not buildable yet.** It implies a scheduled
  interview date/time. Nothing in the schema has one —
  `ApplicationStatus.INTERVIEWING` exists, but there's no
  `scheduled_at`/calendar field anywhere, and no calendar integration.
  Deferred for the same reason as "new match."
- **Conclusion**: this phase ships real auth + the real publish/subscribe
  wiring + Mongo logging + the blocking-call exercise, using
  `tailoring_ready` as the one concrete event. The event shape is designed
  to take a `type` field generically, so adding `new_match` /
  `interview_reminder` later is just a new publish call once those
  features exist — not a schema change.

## Chunks

- [x] **1. Real auth on the WebSocket upgrade** — replaced the
      `?userId=` query param with reading the `jobpilot_session` cookie
      off the upgrade request and verifying it the same way agent-core's
      `get_current_user` does (same `JWT_SECRET`/`HS256`, shared via
      `.env`), using `jsonwebtoken` + `cookie` (both pure-JS, no native
      deps — no repeat of chunk 6's WeasyPrint apt-package risk from
      Phase 4). Rejection happens in `verifyClient`, which runs *before*
      the WebSocket handshake completes — a bad request gets a real HTTP
      401 and the connection never reaches `connectionsByUser` at all,
      rather than being accepted and only then discovered to have no
      real user behind it.
      **Verified for real** against the live container (not mockable in
      any meaningful way — this *is* the real HTTP/WS handshake): a raw
      upgrade request with no cookie got `401 Unauthorized`; the same
      request with a garbage/invalid cookie also got `401`; the same
      request with a real session cookie (reused from Phase 4's test
      user) got a real `101 Switching Protocols`.
- [x] **2. The real publish side** — `publish_event(user_id, event_type,
      payload)` added to `shared/jobpilot_shared/redis_client.py`
      (Python — agent-core/job-worker are the publishers, Notify is the
      only subscriber). Wired into both places `Application.status`
      becomes `READY_TO_APPLY` (`prepare_tasks.py`'s direct-completion
      path, `prepare.py`'s `/approve`), publishing `{"userId", "type":
      "tailoring_ready", "payload": {applicationId, jobPostingId}}` onto
      `jobpilot:events`. Explicitly fire-and-forget (documented in the
      function's own docstring) — `PUBLISH` has no persistence or
      delivery guarantee, which is exactly why chunk 3's Mongo log is a
      separate write, not something this call provides for free.
- [x] **3. Log every event to MongoDB** on the Notify side — a
      `notify_events` collection via the `mongodb` npm driver, written
      when a message arrives off the Redis channel, before the push to
      any connected socket, so there's a durable record even if the user
      isn't connected at the moment it fires. `/ready` now checks Mongo
      too, same per-dependency-checks shape as every other service.

      **Verification note — Gemini's free-tier daily quota (20/day) ran
      out mid-session** (`RESOURCE_EXHAUSTED`, ~18h lockout, confirmed in
      `job-worker` logs — an external constraint, not a bug this phase
      introduced), so a fresh real `/prepare -> /approve` run wasn't
      possible to prove this through that exact call site right now.
      Verified the actual mechanism instead, which `publish_event()` is
      identical through regardless of caller: started a real authenticated
      WebSocket connection (chunk 1's real cookie auth) from inside the
      `notify` container's own network, then called `publish_event()`
      directly from a `job-worker` container with the real test user's
      UUID and a `tailoring_ready` payload. Confirmed, in order: the event
      was logged to `notify_events` in MongoDB (`db.notify_events.find()`
      showed the exact document, with `receivedAt`) and pushed live over
      the open WebSocket to the connected client in real time. The two
      call sites in `prepare_tasks.py`/`prepare.py` are a single
      `publish_event(...)` call each, already covered by Phase 4's
      existing real end-to-end verification of those exact code paths
      minus this one line — worth one more real pass through `/approve`
      itself once quota resets, to be thorough, but not blocking.
- [x] **4. The deliberate blocking-call exercise** — `notify/blocking_demo.js`,
      a standalone script deliberately kept separate from `index.js`'s
      real message handler, so the broken variant it demonstrates is never
      reachable through the actual `jobpilot:events` pub/sub path. It
      spins up a throwaway WS server mirroring Notify's shape, connects
      two clients (A triggers a synchronous CPU-bound SHA-256 hash loop;
      B just pings continuously and times each round trip), and runs both
      a broken and a fixed variant of the same 2-second block.
      **Verified with real measured numbers** (run inside the actual
      `jobpilot-notify` container): **broken** — client B's ping latency
      spiked to a **2003ms** max during the 2000ms synchronous block (only
      49 pings got through the whole window, each one stuck behind
      whichever hash loop iteration was running) — proving Node's
      single-threaded event loop means a synchronous call in *any*
      connection's handler freezes *every* connection the process holds,
      not just the one that triggered it. **Fixed** — moving the identical
      hashing work into a `worker_threads` Worker: client B's max latency
      dropped to **6ms** (avg 0.6ms) during the same 2000ms window, and
      throughput nearly tripled (145 pings got through instead of 49),
      since the main thread's event loop was never blocked at all.
