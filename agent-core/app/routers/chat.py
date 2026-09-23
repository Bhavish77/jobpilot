"""Basic LangChain chatbot — Phase 1's version, before it's a LangGraph
supervisor with specialist agents (Phase 2).

Every real LLM call goes through `acquire_llm_permit()` first: the Redis
token bucket sized to the actual provider RPM, shared across every worker
and every request path, not per-user or per-process. If the bucket is
empty we return 429 rather than let the call through and blow the budget —
the design-doc decision was to gate *before* the call, not retry after a
provider-side rate-limit error.
"""

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from jobpilot_shared.config import settings
from jobpilot_shared.models import User
from jobpilot_shared.redis_client import acquire_llm_permit

from app.deps import get_current_user

router = APIRouter(prefix="/chat", tags=["chat"])

SYSTEM_PROMPT = (
    "You are JobPilot's assistant. You help the user with their job search — "
    "answering questions about their resume, target roles, and the application "
    "process. You never submit job applications yourself; you only prepare "
    "materials and advice for the user to act on."
)


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


def _get_llm() -> ChatGoogleGenerativeAI:
    # Swappable by LLM_PROVIDER/LLM_MODEL later (Phase 10 BYOK adds a
    # per-request override instead of one process-wide client). For now,
    # one client built from the managed-key settings — Gemini Flash, free
    # tier, via a key from Google AI Studio (not the Google OAuth client
    # id/secret used for login — different credential, different console).
    return ChatGoogleGenerativeAI(model=settings.llm_model, google_api_key=settings.llm_api_key)


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, user: User = Depends(get_current_user)) -> ChatResponse:
    permitted = await acquire_llm_permit()
    if not permitted:
        raise HTTPException(
            status_code=429,
            detail="LLM rate limit reached — try again shortly.",
        )

    llm = _get_llm()
    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=req.message)]

    try:
        result = await llm.ainvoke(messages)
    except Exception as exc:  # noqa: BLE001 - Phase 4 wraps this in a real circuit breaker
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}") from exc

    return ChatResponse(reply=result.content)
