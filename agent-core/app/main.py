"""Agent Core — FastAPI service.

Phase 0 gave us /health and /ready. Phase 1 adds the real surface:
email+password/Google login (GitHub optional, connected later for RAG), a
basic chatbot gated by the shared rate limiter, and a cache-aside job
listing endpoint.
"""

from fastapi import FastAPI

from jobpilot_shared import db, mongo, redis_client

from app.routers import auth, chat, jobs

app = FastAPI(title="JobPilot Agent Core")

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(jobs.router)


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
