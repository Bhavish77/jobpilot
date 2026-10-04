"""Chatbot endpoint — Phase 2, chunk 1: now runs through the LangGraph graph
in `app/graph/graph.py` instead of calling the LLM directly. Behavior is
unchanged from Phase 1 (single-turn, no memory across requests yet — that's
chunk 2); only the internal plumbing changed.

Rate limiting happens inside the graph now (app/graph/llm.py's call_llm),
not here — a router-level check only ever accounted for one real call, and
prepare_graph makes several per run (the bug this fixed, found while
reviewing for Phase 4). RateLimitExceeded is what call_llm raises when the
bucket's empty; caught here and turned into a 429.
"""

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from jobpilot_shared.models import User

from app.deps import get_current_user
from app.graph.graph import graph
from app.graph.llm import RateLimitExceeded, extract_text

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, user: User = Depends(get_current_user)) -> ChatResponse:
    try:
        result = await graph.ainvoke({"messages": [HumanMessage(content=req.message)]})
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - Phase 4 wraps this in a real circuit breaker
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}") from exc

    last_message = result["messages"][-1]
    return ChatResponse(reply=extract_text(last_message.content))
