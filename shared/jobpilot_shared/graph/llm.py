"""Shared LLM client + response parsing for every graph node.

`get_llm()` is the *only* place in the codebase that knows which provider
we're using. Every node just calls it and treats the result as a generic
LangChain chat model — that's what makes swapping providers a config change
instead of a rewrite: every provider's LangChain integration implements the
same interface (`.ainvoke(messages)` in, an `AIMessage` out), so nothing
downstream cares which one actually ran.

`init_chat_model` (LangChain's own factory, not something we hand-rolled)
parses a "provider:model" string and dynamically imports whichever provider
package that names, with a *unified* `api_key` kwarg regardless of provider
— nicer than hand-writing an if/elif per provider's differently-named key
(google_api_key vs. api_key vs. anthropic_api_key). LLM_PROVIDER must match
LangChain's own provider key exactly — Gemini-via-AI-Studio (what we use)
is "google_genai", not "google"; that provider's package still has to be
installed (init_chat_model doesn't install anything, just imports it).

To swap providers: set LLM_PROVIDER/LLM_MODEL/LLM_API_KEY in .env, add that
provider's package to agent-core/requirements.txt if it's not already
there, rebuild. No node/graph/prompt code changes needed.

`call_llm()` is the *only* place that should ever actually invoke the
model. CLAUDE.md's standing rule is "every LLM call goes through
acquire_llm_permit() first" — found and fixed a real gap where
prepare_graph's four nodes (draft_resume, draft_cover_letter,
generate_curriculum, review_and_revise) each called the model directly,
completely ungated, since chunk 3. A router-level check (what chat.py/
interview.py did) under-counts here: prepare_graph makes 3-4 real calls
per run, not one, so one permit check per request would only ever account
for a quarter of the actual usage. Enforcing it inside the shared call
site, used by every node, is the only way it can't be forgotten again.

Two gates now, not one (see redis_client.py's module docstring for why
RPM and daily-quota are genuinely different axes) — checked RPM first,
daily quota second, deliberately in that order: RPM tokens refill on
their own, so "wasting" one on a call that then gets blocked by the
daily cap is cheap and self-healing. A daily-quota slot is the opposite
— precious and irreplaceable until tomorrow — so it's only ever spent
once we already know the call is otherwise about to actually happen.
"""

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel, BaseMessage

from jobpilot_shared.config import settings
from jobpilot_shared.redis_client import acquire_daily_quota, acquire_llm_permit


class RateLimitExceeded(Exception):
    """Raised when either the RPM bucket or the daily quota has nothing left."""


def get_llm() -> BaseChatModel:
    return init_chat_model(f"{settings.llm_provider}:{settings.llm_model}", api_key=settings.llm_api_key)


async def call_llm(messages: list) -> BaseMessage:
    if not await acquire_llm_permit():
        raise RateLimitExceeded("LLM rate limit reached — try again shortly.")
    if not await acquire_daily_quota():
        raise RateLimitExceeded(
            f"Daily LLM quota ({settings.llm_daily_quota} calls) reached for today — resets tomorrow (UTC)."
        )
    return await get_llm().ainvoke(messages)


def extract_text(content: str | list) -> str:
    """Gemini responses come back as a list of structured content blocks
    (`[{"type": "text", "text": "..."}]`), not a plain string like OpenAI's
    `.content` used to be — normalize either shape to plain text."""
    if isinstance(content, str):
        return content
    return "".join(block.get("text", "") for block in content if isinstance(block, dict))
