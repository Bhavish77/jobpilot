"""POST /interview/turn — Phase 2, chunk 6.

The curriculum is no longer generated here (chunk 5b's lazy generate-or-skip
moved into /prepare's parallel fan-out — see prepare_graph.py). This router
now just reads the already-persisted curriculum off the Application row and
requires it to exist: if a user somehow reaches Interview Prep for a job
that was never run through /prepare, that's a real precondition failure
(per the design doc, Job Workspace — where Interview Prep's chat tab lives —
is only reachable from a Pipeline card, which only exists once Prepare has
been clicked), not something to silently work around.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jobpilot_shared.db import get_session
from jobpilot_shared.models import Resume, User

from app.applications import get_or_create_application
from app.deps import get_current_user
from jobpilot_shared.graph.llm import RateLimitExceeded, extract_text

router = APIRouter(prefix="/interview", tags=["interview"])


class InterviewTurnRequest(BaseModel):
    job_posting_id: str
    job_description: str
    message: str


@router.get("/{job_posting_id}/history")
async def interview_history(
    job_posting_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Phase 6, chunk 0d: without this, reopening a Job Workspace's
    Interview Prep tab always started blank even though the conversation
    is genuinely still there — the checkpointer already persists the full
    message list, nothing ever read it back. Same aget_state pattern
    /prepare/status already established, applied to interview_graph
    instead of prepare_graph."""
    application = await get_or_create_application(session, user.id, job_posting_id)

    graph = request.app.state.interview_graph
    config = {"configurable": {"thread_id": f"{user.id}:{application.id}"}}
    snapshot = await graph.aget_state(config)

    messages = snapshot.values.get("messages", []) if snapshot.values else []
    return {
        "messages": [
            {"role": "user" if msg.type == "human" else "assistant", "content": extract_text(msg.content)}
            for msg in messages
        ]
    }


@router.post("/turn")
async def interview_turn(
    req: InterviewTurnRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    application = await get_or_create_application(session, user.id, req.job_posting_id)

    if not application.interview_curriculum:
        raise HTTPException(
            status_code=409,
            detail="No interview curriculum yet for this job — run /prepare first.",
        )

    result = await session.execute(
        select(Resume)
        .where(Resume.user_id == user.id, Resume.is_active.is_(True))
        .order_by(Resume.created_at.desc())
    )
    resume = result.scalars().first()
    resume_content = resume.content if resume else ""

    graph = request.app.state.interview_graph
    config = {"configurable": {"thread_id": f"{user.id}:{application.id}"}}

    try:
        final_state = await graph.ainvoke(
            {
                "messages": [HumanMessage(content=req.message)],
                "job_description": req.job_description,
                "resume_content": resume_content,
                "curriculum": application.interview_curriculum,
            },
            config=config,
        )
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - Phase 4 wraps this in a real circuit breaker
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}") from exc

    last_message = final_state["messages"][-1]
    return {"reply": extract_text(last_message.content)}
