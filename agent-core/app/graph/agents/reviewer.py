"""Reviewer — Phase 2, chunks 7 and 8.

Drafter -> reviewer critique-and-revise (the `ai-job-search` idea from
docs/DESIGN_DECISIONS.md): one pass after Resume and Cover Letter are both
drafted, checking for missed JD keywords, weak/generic phrasing, and
resume/cover-letter inconsistency, then proposing improved versions of
both. One combined LLM call rather than two separate review calls per
artifact — same guardrail as the Resume Agent applies here too, since a
review pass is just as capable of introducing fabrication as the original
draft was.

Scoped to Resume/Cover Letter only, per docs/DESIGN_DECISIONS.md's wording
("after a specialist agent (Resume/Cover Letter) produces a draft") —
Interview Prep's curriculum isn't reviewed here; it runs in a separate
parallel branch that never shares a node with this one (see
prepare_graph.py's fan-out, chunk 6).

Chunk 8 splits this into two nodes on purpose. `review_and_revise` does the
expensive LLM call and stores its result as a *proposal*, not a final
value. `await_review_approval` does nothing but call `interrupt()` and act
on the human's decision. They're separate because LangGraph re-runs a node
from scratch on resume — if the LLM call and the interrupt lived in the
same node, approving a review would mean paying for and re-running that
LLM call a second time for no reason.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt

from app.graph.llm import call_llm, extract_text
from app.graph.prepare_state import PrepareState

REVIEW_PROMPT = (
    "You are a critical reviewer checking a tailored resume and cover letter "
    "against a target job description, right before they're sent to the "
    "candidate. Look for: keywords from the JD that are missing but could "
    "honestly be included given the candidate's real background, weak or "
    "generic phrasing that undersells real experience, and any inconsistency "
    "between the resume and cover letter. Fix what you find; if something is "
    "already strong, leave it as-is rather than changing it for its own sake. "
    "Do not introduce any new employer, job title, degree, certification, "
    "second job, or fabricated metric that wasn't already in the drafts you "
    "were given — you are reviewing, not re-drafting from scratch.\n\n"
    "Output exactly this format, with no extra commentary before or after:\n"
    "===RESUME===\n<the improved resume, plain text>\n"
    "===COVER_LETTER===\n<the improved cover letter, plain text>"
)


async def review_and_revise(state: PrepareState) -> dict:
    user_prompt = (
        f"Job description:\n{state['job_description']}\n\n"
        f"Draft resume:\n{state['resume_output']}\n\n"
        f"Draft cover letter:\n{state['cover_letter_output']}"
    )
    messages = [SystemMessage(content=REVIEW_PROMPT), HumanMessage(content=user_prompt)]
    result = await call_llm(messages)
    text = extract_text(result.content)

    if "===RESUME===" in text and "===COVER_LETTER===" in text:
        resume_part, cover_letter_part = text.split("===COVER_LETTER===", 1)
        revised_resume = resume_part.split("===RESUME===", 1)[1].strip()
        # Proposal only — originals stay untouched until a human approves.
        return {
            "proposed_resume": revised_resume,
            "proposed_cover_letter": cover_letter_part.strip(),
            "status": "review_pending_approval",
        }

    # Model didn't follow the delimiter format — nothing to propose; the
    # originals stand as final with no approval step needed.
    return {"status": "review_parse_failed"}


async def await_review_approval(state: PrepareState) -> dict:
    """The only job of this node is to pause and wait — no LLM call here on
    purpose, so resuming after approval never re-runs (or re-pays for) the
    expensive review_and_revise call above."""
    if not state.get("proposed_resume"):
        # review_and_revise had nothing to propose — nothing to approve.
        return {}

    decision = interrupt(
        {
            "original_resume": state["resume_output"],
            "proposed_resume": state["proposed_resume"],
            "original_cover_letter": state["cover_letter_output"],
            "proposed_cover_letter": state["proposed_cover_letter"],
        }
    )

    if decision == "accept":
        return {
            "resume_output": state["proposed_resume"],
            "cover_letter_output": state["proposed_cover_letter"],
            "status": "reviewed_accepted",
        }
    return {"status": "reviewed_kept_original"}
