"""POST /prepare and POST /prepare/{job_posting_id}/approve.

Phase 2, chunk 8: /prepare can now come back in a "pending_review" state
instead of a final one — the graph paused inside await_review_approval,
waiting on a human decision. /approve resumes it with that decision via
Command(resume=...), which continues execution from the interrupt point
(not from the start — review_and_revise's LLM call already ran and
checkpointed its result, so approving doesn't re-run or re-pay for it).
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from langgraph.types import Command
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jobpilot_shared.db import get_session
from jobpilot_shared.models import Application, Resume, User

from app.applications import get_or_create_application
from app.deps import get_current_user
from app.graph.llm import RateLimitExceeded

router = APIRouter(prefix="/prepare", tags=["prepare"])


class PrepareRequest(BaseModel):
    job_posting_id: str
    job_description: str


class ApproveRequest(BaseModel):
    decision: Literal["accept", "reject"]


def _thread_config(user_id, application_id) -> dict:
    # ":prepare" suffix keeps this distinct from /interview's thread_id for
    # the same application — same checkpointer/tables, different threads.
    return {"configurable": {"thread_id": f"{user_id}:{application_id}:prepare"}}


def _result_payload(result: dict) -> dict:
    return {
        "status": result.get("status"),
        "resume_output": result.get("resume_output"),
        "cover_letter_output": result.get("cover_letter_output"),
        "curriculum": result.get("curriculum"),
    }


async def _persist(session: AsyncSession, application: Application, result: dict) -> None:
    application.resume_output = result.get("resume_output")
    application.cover_letter_output = result.get("cover_letter_output")
    application.interview_curriculum = result.get("curriculum")
    await session.commit()


@router.post("")
async def prepare(
    req: PrepareRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    application = await get_or_create_application(session, user.id, req.job_posting_id)

    result = await session.execute(
        select(Resume)
        .where(Resume.user_id == user.id, Resume.is_active.is_(True))
        .order_by(Resume.created_at.desc())
    )
    resume = result.scalars().first()
    resume_content = resume.content if resume else ""

    graph = request.app.state.prepare_graph
    config = _thread_config(user.id, application.id)

    try:
        final_state = await graph.ainvoke(
            {
                "user_id": str(user.id),
                "job_description": req.job_description,
                "resume_content": resume_content,
            },
            config=config,
        )
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - Phase 4 wraps this in a real circuit breaker
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}") from exc

    if final_state.get("__interrupt__"):
        payload = final_state["__interrupt__"][0].value
        return {"status": "pending_review", "review": payload}

    if not final_state["quality_ok"]:
        raise HTTPException(status_code=422, detail=final_state["rejection_reason"])

    await _persist(session, application, final_state)
    return _result_payload(final_state)


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

    await _persist(session, application, final_state)
    return _result_payload(final_state)
