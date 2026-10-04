# Phase 3 — RAG: resume + GitHub — implementation plan

Working doc for the current phase, same spirit as `PHASE_2_PLAN.md`. Delete
or archive once Phase 3 actually ships.

**Goal, from ROADMAP.md**: chunk + embed resume/portfolio, GitHub ingestion
layered in, Chroma vector store, hybrid search, agentic RAG, basic
RAGAS-style eval.

## Scope, revised before writing any code

Traced through what actually needs retrieval, same way Phase 2 traced
through what actually needed a supervisor/parallel branch/interrupt — and
the answer right now is: nothing does.

- **GitHub ingestion deferred** (explicit user call) — the part of this
  phase that would have produced a corpus big enough to need retrieval.
- **Resume-only RAG doesn't need to exist.** Retrieval solves exactly one
  problem: too much content to affordably fit in the model's context
  window, so fetch only the most relevant slice. A single resume is 5-15
  chunks, a page or two of text — nowhere close to that problem, especially
  against Gemini's actual context window (1M tokens on the current Flash
  model). Dumping the whole resume (what `draft_resume`/`generate_curriculum`
  already do today) costs nothing extra and guarantees the model sees 100%
  of the real information. Retrieval over a corpus this small can only
  *drop* real signal that scored "not relevant enough" — strictly worse
  engineering for this specific case, not just unneeded complexity.
- So **chunking, embeddings, and a vector store are all deferred alongside
  GitHub ingestion** — they get built together, whenever a corpus actually
  big enough to need them shows up (GitHub repos/READMEs/code, multiple
  documents searched at once). Building them against today's single-resume
  corpus would mean infrastructure with nothing real to operate on.
- **Hybrid search and "agentic RAG"** (an LLM deciding when/what to
  retrieve via tool-calling) are further out still — they solve problems
  that only show up once plain dense retrieval is already real and already
  insufficient. Don't reach for them before dense retrieval itself has a
  job to do.

**What's actually being built now**: just the resume upload endpoint — a
real, standing gap since Phase 2 started (every test this whole phase has
needed a manual `INSERT INTO resumes ...` via psql instead of a real API).

## Decisions made along the way, for whenever RAG actually gets built

- **Vector store: pgvector, not Chroma.** The roadmap listed Chroma as
  primary and pgvector as a "stretch, compare" — flipped, now that it's
  sized against our real numbers instead of a generic tutorial's
  assumptions. Current guidance: pgvector is the right starting point
  specifically when you already run Postgres and have under
  ~500K-10M vectors; dedicated vector DBs (Qdrant/Weaviate/Pinecone) only
  start winning past that scale or when you need purpose-built ANN
  performance. JobPilot already runs Postgres and will stay comfortably
  under that ceiling for a long time — Chroma would mean a whole separate
  piece of infrastructure (another container, another connection, another
  backup story) for a workload that fits trivially inside a database we
  already operate.
- **Embeddings: Gemini's embedding model, not a second provider.** Already
  fully on Gemini for generation (same API key, same billing, free tier).
  Switching providers just for embeddings would be pure friction for no
  real benefit. Wire it through LangChain's `init_embeddings("google_genai:
  <model>", ...)` — the embeddings equivalent of the `init_chat_model`
  pattern already in `app/graph/llm.py`. Exact model id to confirm against
  the real API when this is actually built (same lesson as the chat-model
  naming surprise back in Phase 2) — references turned up both
  `gemini-embedding-001` and a newer `gemini-embedding-2`/
  `-2-preview`.
- **Chunking: structure-aware, not fixed-size windows.** Generic RAG advice
  (fixed token windows with overlap) is for long unstructured prose where
  there's no other boundary to exploit. A resume has obvious structural
  sections (Summary, Skills, one block per job in Experience, Education,
  Projects) — fixed-size chunking risks slicing a bullet point in half
  mid-sentence. Plan: one LLM call at upload time to split into natural
  sections (one chunk per job entry, not one chunk per N characters) rather
  than brittle regex/heading-detection heuristics, which don't hold up
  against how much resume formatting varies.

## Chunks

- [x] **1. Resume upload endpoint** — `POST /resumes` (create + activate,
      deactivating any previous active resume so the one-active-resume
      invariant every existing query already assumes stays true),
      `GET /resumes/active`. Updated the dev harness with a Resume section
      and fixed `/prepare`'s now-stale "no upload UI yet" note, closing the
      manual-SQL-insert gap used throughout all of Phase 2 testing.
      **Verified**: uploaded via the real endpoint (no SQL), fetched it
      back correctly; uploaded a second resume and confirmed in Postgres
      that exactly one row stayed `is_active=True` (the new one) — the
      invariant every downstream query depends on actually holds.

**Phase 3 complete, at its revised scope.** Chunking/embeddings/vector
store/hybrid search/agentic RAG all remain deferred alongside GitHub
ingestion, per the scope decision above — pick this doc back up when an
actual corpus shows up to justify them.
