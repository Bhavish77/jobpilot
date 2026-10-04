"""The Prepare pipeline graph.

Chunk 2: a resume-quality gate — the roadmap's "conditional edges on resume
quality," a narrow deterministic check, not a general-purpose routing
supervisor (see docs/PHASE_2_PLAN.md, "Decisions made along the way," for
why a supervisor isn't needed here: "Prepare" always triggers the same
fixed pipeline, so there's no routing *decision* to make — only this one
real fork: is there enough resume content to generate from at all?

Chunk 3: the quality gate's "proceed" path now runs the real Resume Agent
instead of a placeholder.

Chunk 4: Cover Letter runs sequentially after Resume — a plain edge is all
that's needed, since both nodes read/write the same shared `PrepareState`;
`draft_cover_letter` doesn't need `draft_resume`'s output passed to it
explicitly, it just reads `state["resume_output"]` once the graph reaches it.

Chunk 6: `generate_curriculum` now runs *in parallel* with the
Resume -> Cover Letter chain, not sequentially. The routing function returns
a list of node names instead of a single one — LangGraph schedules every
node in that list to run in the same step, which is the actual fan-out
mechanism. No explicit "join" node is needed just to wait for both branches:
`ainvoke` doesn't return until every active branch reaches END, so
`final_state` naturally contains resume_output, cover_letter_output, and
curriculum together once both finish.

Chunk 7: a reviewer pass runs after draft_cover_letter, on the
Resume->Cover Letter branch only — generate_curriculum's parallel branch is
untouched by this, it still goes straight to END on its own.

Chunk 8: a human-in-the-loop approval step after the review, via
await_review_approval's `interrupt()` call. This graph is now exported
*uncompiled* (like interview_graph.py since chunk 5a) — interrupting and
later resuming requires a checkpointer, which can only be attached at
compile time, and only exists once main.py's lifespan opens it at startup.

Phase 4, chunk 1: made retries actually resumable. Checked empirically
(see docs/PHASE_4_PLAN.md) that calling ainvoke with fresh input against an
existing thread_id does *not* skip already-completed nodes the way
Command(resume=...) does for a pending interrupt — a plain retry restarted
the whole graph from START, re-paying for already-finished LLM calls.
`_route_after_quality_check` now inspects what's already in state and
routes straight to whichever step hasn't completed yet, for each branch
independently, instead of always fanning out to draft_resume +
generate_curriculum unconditionally.
"""

from langgraph.graph import END, START, StateGraph

from app.graph.agents.cover_letter import draft_cover_letter
from app.graph.agents.interview_prep import generate_curriculum
from app.graph.agents.resume import draft_resume
from app.graph.agents.reviewer import await_review_approval, review_and_revise
from app.graph.prepare_state import PrepareState

MIN_RESUME_WORDS = 50

# Statuses meaning the Resume->Cover Letter->Review branch has already
# fully resolved — set only by await_review_approval (after a real
# decision) or by review_and_revise finding nothing to propose. Retrying
# past this point would re-trigger an interrupt for a decision that's
# already been made.
_RESUME_BRANCH_DONE_STATUSES = {"reviewed_accepted", "reviewed_kept_original", "review_parse_failed"}


async def check_resume_quality(state: PrepareState) -> dict:
    word_count = len(state["resume_content"].split())
    if word_count < MIN_RESUME_WORDS:
        return {
            "quality_ok": False,
            "rejection_reason": (
                f"Resume content is only {word_count} words — need at least "
                f"{MIN_RESUME_WORDS} to generate a tailored resume from. "
                "Add more detail to your profile first."
            ),
            "status": "insufficient_resume",
        }
    return {"quality_ok": True, "status": "quality_check_passed"}


def _route_after_quality_check(state: PrepareState) -> list[str] | str:
    if not state["quality_ok"]:
        return END

    next_steps = []

    # Resume -> Cover Letter -> Review chain: resume from wherever an
    # earlier attempt (if any) left off, rather than redoing completed,
    # expensive LLM calls on every retry.
    if state.get("status") in _RESUME_BRANCH_DONE_STATUSES:
        pass  # nothing left to do on this branch
    elif not state.get("resume_output"):
        next_steps.append("draft_resume")
    elif not state.get("cover_letter_output"):
        next_steps.append("draft_cover_letter")
    elif not state.get("proposed_resume"):
        next_steps.append("review_and_revise")
    else:
        next_steps.append("await_review_approval")

    # Curriculum branch: independent of the above, resume the same way.
    if not state.get("curriculum"):
        next_steps.append("generate_curriculum")

    return next_steps or END


builder = StateGraph(PrepareState)
builder.add_node("check_resume_quality", check_resume_quality)
builder.add_node("draft_resume", draft_resume)
builder.add_node("draft_cover_letter", draft_cover_letter)
builder.add_node("review_and_revise", review_and_revise)
builder.add_node("await_review_approval", await_review_approval)
builder.add_node("generate_curriculum", generate_curriculum)

builder.add_edge(START, "check_resume_quality")
builder.add_conditional_edges("check_resume_quality", _route_after_quality_check)
builder.add_edge("draft_resume", "draft_cover_letter")
builder.add_edge("draft_cover_letter", "review_and_revise")
builder.add_edge("review_and_revise", "await_review_approval")
builder.add_edge("await_review_approval", END)
builder.add_edge("generate_curriculum", END)
