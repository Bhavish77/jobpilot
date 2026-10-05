"""The Prepare pipeline's Celery task — Phase 4, chunk 4.

One task wraps the *entire* prepare_graph run, per the design-doc revision
(docs/DESIGN_DECISIONS.md, "Why background jobs need a queue") — not four
separate tasks coordinated by Celery's own chain/group/chord, since
LangGraph's edges already own that coordination internally. Depends on
chunk 1's resumable routing: if this task crashes and Celery redelivers it
(task_acks_late=True), re-invoking the same thread_id picks up from
wherever it left off instead of re-paying for finished LLM calls.

Real gap found post-Phase-6 (not caught by any earlier test, because every
earlier real test happened to hit the LLM when it was healthy): the
resumable routing above only ever helps if something actually re-invokes
the task. `task_acks_late=True` only protects against the *worker process*
dying mid-task (OOM/SIGKILL) — an ordinary exception raised *inside* the
task (the worker stays alive, Celery just marks the task FAILED) acks the
message and is gone for good, no redelivery. Hit this for real: a
transient `GoogleAPIError` (503 "high demand, try again later") during
`draft_cover_letter` killed the task outright, leaving an application
checkpointed at 3/6 steps — forever, since nothing was retrying it, while
`/status` kept reporting "in_progress" since nothing distinguishes "still
running" from "ran once, failed, will never run again." Fixed with
Celery's own `autoretry_for`, scoped to `GoogleAPIError` specifically
(confirmed via `issubclass()` that `GoogleRateLimitError` — a sustained
quota exhaustion that can last ~24h — is a *sibling*, not a subclass, so a
real quota lockout correctly does NOT get caught here and retried
pointlessly; only genuinely transient server errors do).

Builds its own checkpointer/compiled graph fresh inside this task's own
asyncio.run() call rather than trying to persist one across calls within
the same long-lived worker process (verified safe for job_tasks.py's
simpler case — SQLAlchemy's pool_pre_ping discards a stale cross-event-loop
connection transparently — but a checkpointer's AsyncConnectionPool is a
more stateful object, not worth risking the same assumption without the
same direct proof).

Must call dispose_engine() before this task's asyncio.run() loop closes —
db.py's module-level engine/pool otherwise binds to this loop and the next
task's own asyncio.run() loop crashes reusing it ("attached to a different
loop"; see db.py's docstring — this is the exact crash that was hit here).
"""

import asyncio

from langchain_google_genai.chat_models import GoogleAPIError
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import select

from jobpilot_shared.celery_app import celery_app
from jobpilot_shared.config import settings
from jobpilot_shared.db import async_session, dispose_engine
from jobpilot_shared.graph.prepare_graph import builder as prepare_graph_builder
from jobpilot_shared.models import Application, ApplicationStatus, Resume
from jobpilot_shared.redis_client import dispose_pool as dispose_redis_pool
from jobpilot_shared.redis_client import publish_event


async def _run_prepare_pipeline(user_id: str, application_id: str, job_description: str) -> dict:
    async with async_session() as session:
        result = await session.execute(
            select(Resume).where(Resume.user_id == user_id, Resume.is_active.is_(True))
            .order_by(Resume.created_at.desc())
        )
        resume = result.scalars().first()
    resume_content = resume.content if resume else ""

    async with AsyncConnectionPool(
        conninfo=settings.checkpointer_conninfo,
        kwargs={"autocommit": True, "row_factory": dict_row},
    ) as pool:
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        graph = prepare_graph_builder.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": f"{user_id}:{application_id}:prepare"}}
        final_state = await graph.ainvoke(
            {"user_id": user_id, "job_description": job_description, "resume_content": resume_content},
            config=config,
        )

    if final_state.get("__interrupt__"):
        return {"status": "pending_review"}

    if not final_state["quality_ok"]:
        return {"status": "insufficient_resume", "rejection_reason": final_state["rejection_reason"]}

    # Reached directly (no interrupt) when review_and_revise had nothing to
    # propose — see prepare_graph.py's await_review_approval. This is the
    # "mark_ready_to_apply" step the original design doc described: the
    # task's own body, once the graph is actually done, flips the Pipeline
    # card instead of a separate chord-callback task.
    async with async_session() as session:
        application = await session.get(Application, application_id)
        application.resume_output = final_state.get("resume_output")
        application.cover_letter_output = final_state.get("cover_letter_output")
        application.interview_curriculum = final_state.get("curriculum")
        application.status = ApplicationStatus.READY_TO_APPLY
        await session.commit()

    await publish_event(
        user_id, "tailoring_ready", {"applicationId": application_id, "jobPostingId": application.job_posting_id}
    )

    return {"status": final_state["status"]}


async def _run_prepare_pipeline_and_dispose(user_id: str, application_id: str, job_description: str) -> dict:
    try:
        return await _run_prepare_pipeline(user_id, application_id, job_description)
    finally:
        await dispose_engine()
        await dispose_redis_pool()


@celery_app.task(
    name="jobpilot.run_prepare_pipeline",
    autoretry_for=(GoogleAPIError,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def run_prepare_pipeline(user_id: str, application_id: str, job_description: str) -> dict:
    # A retry re-invokes this same function from scratch, but
    # _run_prepare_pipeline always resumes the same thread_id, and
    # prepare_graph.py's _route_after_quality_check (chunk 1) skips
    # whatever already completed — a retry after 4/6 steps succeeded
    # only re-pays for the one step that actually failed, not the whole
    # pipeline.
    return asyncio.run(_run_prepare_pipeline_and_dispose(user_id, application_id, job_description))
