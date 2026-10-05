"""Interview Prep's real logic — Phase 2, chunks 5b and 6.

Two nodes, now living in *two different graphs*: `generate_curriculum` runs
once, in parallel with Resume->Cover Letter, as part of prepare_graph.py
(chunk 6) — gap analysis between the candidate's real, *untailored* profile
resume and the JD, never the per-job tailored resume_output (see
PHASE_2_PLAN.md's chunk-5 decisions — the tailored resume is allowed to play
to the JD, so it can't be trusted as the source of real gaps). `interview_turn`
runs on every conversational message, in interview_graph.py, using the
curriculum /prepare already generated. Guidance-only — no submission/grading
loop, see docs/DESIGN_DECISIONS.md, "Interview Prep's curriculum stays
guidance-only."
"""

from langchain_core.messages import HumanMessage, SystemMessage

from jobpilot_shared.graph.llm import call_llm, extract_text
from jobpilot_shared.graph.interview_state import InterviewState

CURRICULUM_PROMPT = (
    "You are a technical interview coach. Compare the candidate's real "
    "background against the target job description and identify genuine "
    "gaps — things the job asks for that the candidate's background shows "
    "no evidence of at all. For each real gap, briefly explain why it "
    "matters for this role, and suggest one small, concrete project or "
    "exercise the candidate could do to build real familiarity with it "
    "before an interview. Do not list a gap for anything the background "
    "already demonstrates, even partially. Output a study curriculum as "
    "plain text, one entry per real gap."
)

INTERVIEW_TURN_PROMPT_TEMPLATE = (
    "You are conducting a mock technical interview for this job description:\n"
    "{job_description}\n\n"
    "The candidate's real background:\n{resume_content}\n\n"
    "Known gaps to probe (from the study curriculum already generated):\n"
    "{curriculum}\n\n"
    "Ask one interview question at a time — mix questions about the "
    "candidate's real, demonstrated experience with questions that "
    "specifically probe the gaps above, so they get practice discussing "
    "unfamiliar territory honestly rather than avoiding it. After the "
    "candidate answers, give brief, honest feedback on their answer, then "
    "ask the next question. Professional tone, not harsh — but don't just "
    "say everything is great."
)


async def generate_curriculum(state: InterviewState) -> dict:
    user_prompt = (
        f"Candidate background:\n{state['resume_content']}\n\n"
        f"Job description:\n{state['job_description']}"
    )
    messages = [SystemMessage(content=CURRICULUM_PROMPT), HumanMessage(content=user_prompt)]
    result = await call_llm(messages)
    return {"curriculum": extract_text(result.content)}


async def interview_turn(state: InterviewState) -> dict:
    system_prompt = INTERVIEW_TURN_PROMPT_TEMPLATE.format(
        job_description=state["job_description"],
        resume_content=state["resume_content"],
        curriculum=state["curriculum"],
    )
    messages = [SystemMessage(content=system_prompt), *state["messages"]]
    result = await call_llm(messages)
    return {"messages": [result]}
