"""POST /prepare, GET /prepare/{job_posting_id}/status, POST /prepare/{job_posting_id}/approve.

Phase 4, chunk 4: /prepare no longer awaits the graph directly — it
enqueues jobpilot.run_prepare_pipeline (shared/jobpilot_shared/prepare_tasks.py)
and returns immediately. The actual multi-LLM-call pipeline (60-180+
seconds, per earlier testing) now runs in job-worker, off the request path.

/status exists because the client has no other way to find out what
happened after that — it reads the *same* checkpointed state job-worker's
graph instance wrote (same Postgres tables, different connection pool),
via agent-core's own already-compiled prepare_graph.

Real gap found post-Phase-6: the checkpointer alone can't tell "still
genuinely running" apart from "the task raised and died, nothing will
ever finish this" — both look identical (state stuck mid-pipeline,
`snapshot.next` still pointing at an unfinished node). Found this for
real: a task died on a transient Gemini 503, and separately on a 429
quota lockout (deliberately *not* auto-retried — see prepare_tasks.py's
docstring for why retrying a ~24h lockout would be pointless) — in both
cases /status kept reporting "in_progress" forever with nothing to tell
the user it had actually stopped. Fixed by persisting the Celery task_id
(`Application.last_prepare_task_id`) and checking its real result state
via Celery's own result backend whenever the checkpoint alone would
otherwise say "in_progress."

/approve stays synchronous, deliberately not enqueued — resuming after an
interrupt is cheap (review_and_revise's LLM call already ran and
checkpointed; nothing after the interrupt makes another LLM call), so
there's nothing here a queue would protect the request path from.
"""

import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from langgraph.types import Command
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jobpilot_shared.db import get_session
from jobpilot_shared.models import ApplicationStatus, JobPosting, User
from jobpilot_shared.prepare_tasks import run_prepare_pipeline
from jobpilot_shared.redis_client import publish_event

from app.applications import get_or_create_application
from app.deps import get_current_user
from jobpilot_shared.graph.llm import RateLimitExceeded

router = APIRouter(prefix="/prepare", tags=["prepare"])


class PrepareRequest(BaseModel):
    job_posting_id: str
    # Optional since chunk 0b: real JobPosting rows already have their
    # own description in Postgres, so a retry (or any caller that only
    # has the id) doesn't need to carry the full text around — it's
    # looked up server-side when omitted. Still accepted directly for
    # ids that aren't real JobPosting rows (older/external data).
    job_description: str | None = None


class ApproveRequest(BaseModel):
    decision: Literal["accept", "reject"]


def _thread_config(user_id, application_id) -> dict:
    # ":prepare" suffix keeps this distinct from /interview's thread_id for
    # the same application — same checkpointer/tables, different threads.
    return {"configurable": {"thread_id": f"{user_id}:{application_id}:prepare"}}


def _result_payload(result: dict) -> dict:
    return {
        "status": result.get("status"),
        "rejection_reason": result.get("rejection_reason"),
        "resume_output": result.get("resume_output"),
        "cover_letter_output": result.get("cover_letter_output"),
        "curriculum": result.get("curriculum"),
        "pdf_check": result.get("pdf_check"),
    }


# Mirrors prepare_graph.py's real node shape (check_resume_quality ->
# draft_resume -> draft_cover_letter -> review_and_revise ->
# await_review_approval -> compile_and_fit_resume, with generate_curriculum
# running in parallel) — not a fake fixed-duration progress bar. Each
# step's "done" is read straight off the same checkpointed state fields
# the graph itself routes on (prepare_graph.py's _route_after_quality_check),
# so this can never claim a step finished before the graph actually did it.
_TERMINAL_REVIEW_STATUSES = {"reviewed_accepted", "reviewed_kept_original", "review_parse_failed", "resume_finalized"}


def _compute_steps(values: dict) -> list[dict]:
    status = values.get("status")
    return [
        {
            "key": "quality_check",
            "label": "Checking your resume",
            "done": values.get("quality_ok") is not None,
        },
        {
            "key": "resume",
            "label": "Drafting your tailored resume",
            "done": bool(values.get("resume_output")),
        },
        {
            "key": "cover_letter",
            "label": "Writing your cover letter",
            "done": bool(values.get("cover_letter_output")),
        },
        {
            "key": "curriculum",
            "label": "Building your interview prep curriculum",
            "done": bool(values.get("curriculum")),
        },
        {
            "key": "review",
            "label": "Reviewing & polishing",
            "done": bool(values.get("proposed_resume")) or status in _TERMINAL_REVIEW_STATUSES,
        },
        {
            "key": "finalize",
            "label": "Verifying ATS formatting",
            "done": status == "resume_finalized",
        },
    ]


# Gemini's own message has the form "...retry in 11h42m23.6102s." — hours
# and minutes are worth showing, the fractional seconds aren't (nobody
# needs "23.6102s" of precision on a multi-hour wait).
_RETRY_AFTER_RE = re.compile(r"retry in (?:(\d+)h)?(?:(\d+)m)?(\d+)(?:\.\d+)?s", re.IGNORECASE)


def _format_retry_after(hours: str | None, minutes: str | None, seconds: str) -> str:
    parts = []
    if hours and int(hours) > 0:
        parts.append(f"{hours}h")
    if minutes and int(minutes) > 0:
        parts.append(f"{minutes}m")
    if not parts:  # under a minute left — seconds are the only useful unit
        parts.append(f"{seconds}s")
    return " ".join(parts)


def _friendly_task_error(raw: str) -> str:
    """Best-effort translation of a raw Celery/LLM exception string into
    something worth showing a user — not every failure is a rate limit,
    but that's the one we know how to say something specific about."""
    # Our own RateLimitExceeded messages (llm.py) are already written to
    # be shown directly — either our RPM bucket or our daily-quota gate
    # caught this *before* the call ever reached the provider, so there's
    # no provider error text to parse in the first place.
    if "Daily LLM quota" in raw or "LLM rate limit reached" in raw:
        return raw

    # Otherwise this is the provider's own raw error — Gemini's message
    # already states how long until it resets, so parse that out instead
    # of a bare "try again later."
    if "RESOURCE_EXHAUSTED" in raw or "rate limit" in raw.lower():
        match = _RETRY_AFTER_RE.search(raw)
        if match:
            wait = _format_retry_after(*match.groups())
            return f"The AI provider's free-tier limit was reached — try again in about {wait}."
        return "The AI provider's rate limit was reached — try again shortly."
    return "Something went wrong while preparing this application. Try again."


async def _resolve_job_description(session: AsyncSession, job_posting_id: str, provided: str | None) -> str:
    if provided:
        return provided
    try:
        posting_uuid = UUID(job_posting_id)
    except ValueError:
        posting_uuid = None
    posting = None
    if posting_uuid is not None:
        posting = await session.get(JobPosting, posting_uuid)
    if posting is None:
        raise HTTPException(
            status_code=400,
            detail="job_description is required for a job posting id that isn't a real JobPosting row.",
        )
    return posting.description


@router.post("")
async def prepare(
    req: PrepareRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    application = await get_or_create_application(session, user.id, req.job_posting_id)
    job_description = await _resolve_job_description(session, req.job_posting_id, req.job_description)

    task = run_prepare_pipeline.delay(str(user.id), str(application.id), job_description)

    application.last_prepare_task_id = task.id
    await session.commit()

    return {"status": "preparing", "task_id": task.id}


@router.get("/{job_posting_id}/status")
async def status(
    job_posting_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    application = await get_or_create_application(session, user.id, job_posting_id)

    graph = request.app.state.prepare_graph
    config = _thread_config(user.id, application.id)
    snapshot = await graph.aget_state(config)

    if not snapshot.values:
        return {"status": "not_started", "steps": _compute_steps({})}

    if snapshot.interrupts:
        return {
            "status": "pending_review",
            "review": snapshot.interrupts[0].value,
            "steps": _compute_steps(snapshot.values),
        }

    if snapshot.next:
        # The checkpoint alone can't tell "still genuinely running" apart
        # from "the task raised and died" — both look identical here
        # (state stuck mid-pipeline, snapshot.next still pointing at an
        # unfinished node). Only the task's own Celery result state
        # actually knows the difference.
        if application.last_prepare_task_id:
            result = run_prepare_pipeline.AsyncResult(application.last_prepare_task_id)
            if result.state == "FAILURE":
                return {
                    "status": "failed",
                    "error": _friendly_task_error(str(result.result)),
                    "steps": _compute_steps(snapshot.values),
                }
        return {"status": "in_progress", "steps": _compute_steps(snapshot.values)}

    return {**_result_payload(snapshot.values), "steps": _compute_steps(snapshot.values)}


@router.post("/{job_posting_id}/approve")
async def approve(
    job_posting_id: str,
    req: ApproveRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    application = await get_or_create_application(session, user.id, job_posting_id)

    graph = request.app.state.prepare_graph
    config = _thread_config(user.id, application.id)

    try:
        final_state = await graph.ainvoke(Command(resume=req.decision), config=config)
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}") from exc

    application.resume_output = final_state.get("resume_output")
    application.cover_letter_output = final_state.get("cover_letter_output")
    application.interview_curriculum = final_state.get("curriculum")
    # Both "accept" and "reject" land here with a final resume/cover letter
    # ready to use (reject just means the originals stand, not that
    # anything failed) — either way the Pipeline card is ready to apply.
    application.status = ApplicationStatus.READY_TO_APPLY
    await session.commit()

    await publish_event(
        str(user.id), "tailoring_ready", {"applicationId": str(application.id), "jobPostingId": job_posting_id}
    )

    return {**_result_payload(final_state), "steps": _compute_steps(final_state)}
