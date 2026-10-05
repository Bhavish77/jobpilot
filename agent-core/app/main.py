"""Agent Core — FastAPI service.

Phase 0 gave us /health and /ready. Phase 1 adds the real surface:
email+password/Google login (GitHub optional, connected later for RAG), a
basic chatbot gated by the shared rate limiter, and a cache-aside job
listing endpoint. Phase 2 adds the LangGraph Prepare pipeline and, from
chunk 5, Postgres-backed conversation memory for Interview Prep.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from jobpilot_shared import db, mongo, redis_client
from jobpilot_shared.config import settings

from jobpilot_shared.graph.interview_graph import builder as interview_graph_builder
from jobpilot_shared.graph.prepare_graph import builder as prepare_graph_builder
from app.routers import applications, auth, chat, interview, jobs, prepare, resumes


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The checkpointer needs its own connection pool — separate from the
    # SQLAlchemy engine in jobpilot_shared.db, since it talks to Postgres
    # directly via psycopg, not through the ORM. Opened once here (one pool
    # per worker process, shared across every request that process handles)
    # rather than per-request, same reasoning as every other connection
    # pool in this codebase.
    async with AsyncConnectionPool(
        conninfo=settings.checkpointer_conninfo,
        kwargs={"autocommit": True, "row_factory": dict_row},
    ) as pool:
        checkpointer = AsyncPostgresSaver(pool)
        # LangGraph manages its own checkpoint tables — separate from
        # Alembic/models.py entirely. .setup() creates them if missing;
        # safe to call on every startup.
        await checkpointer.setup()
        # Both graphs share this one checkpointer/pool — no reason to open a
        # second connection pool just because a second graph needs
        # persistence. Their thread_id strings (see prepare.py/interview.py)
        # stay distinct so neither graph's checkpoints collide with the
        # other's under the same underlying tables.
        app.state.interview_graph = interview_graph_builder.compile(checkpointer=checkpointer)
        app.state.prepare_graph = prepare_graph_builder.compile(checkpointer=checkpointer)
        yield


app = FastAPI(title="JobPilot Agent Core", lifespan=lifespan)

# Phase 6: the frontend is a separate origin (:3000 vs :8000) and every
# request needs the session cookie, so this must be the real origin, not
# "*" — browsers refuse "*" + credentials together regardless.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(jobs.router)
app.include_router(prepare.router)
app.include_router(interview.router)
app.include_router(resumes.router)
app.include_router(applications.router)

# Dev-only test harness (click-through auth/chat/jobs without curl) — NOT
# Phase 6's real frontend, which is a separate Next.js app on its own origin
# and will need CORS here once it exists. This page is same-origin, so it
# needs none. Served at /dev/, e.g. http://localhost:8000/dev/
app.mount("/dev", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="dev-harness")


@app.get("/health")
async def health() -> dict:
    """Liveness — is the process up at all. Never checks dependencies."""
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict:
    """Readiness — can this instance actually serve traffic right now."""
    checks = {}
    try:
        checks["postgres"] = await db.ping()
    except Exception as exc:  # noqa: BLE001 - surfacing the failure is the point
        checks["postgres"] = f"error: {exc}"
    try:
        checks["mongo"] = await mongo.ping()
    except Exception as exc:  # noqa: BLE001
        checks["mongo"] = f"error: {exc}"
    try:
        checks["redis"] = await redis_client.ping()
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {exc}"

    ok = all(v is True for v in checks.values())
    return {"status": "ready" if ok else "degraded", "checks": checks}
