"""Resume Agent — Phase 2, chunk 3.

Drafts a tailored resume from the candidate's real stored background plus a
target job description. This isn't retrieval-augmented yet (Phase 3 adds
real RAG); for now the entire stored resume is passed in directly, since
there's nothing to retrieve *from* yet.

Note on the one guardrail this prompt keeps (see docs/PHASE_2_PLAN.md,
"Decisions made along the way"): this is a per-job *tailored* draft, allowed
to frame real experience as strongly as the JD calls for — the candidate's
honest, untailored profile resume lives separately (`resumes` table) and is
what Interview Prep reads from later to find real knowledge gaps, so this
agent leaning into aggressive framing doesn't corrupt that gap analysis.
"""

from langchain_core.messages import HumanMessage, SystemMessage

from app.graph.llm import call_llm, extract_text
from app.graph.prepare_state import PrepareState

RESUME_AGENT_PROMPT = (
    "You are a resume-writing assistant. Given a candidate's background and "
    "a target job description, draft the strongest possible tailored resume "
    "for this specific job — match the JD's language, emphasize whatever "
    "real experience is most relevant, and frame it as persuasively as the "
    "underlying work supports. Job descriptions routinely inflate "
    "requirements (e.g. asking for '10 years' of a technology that's only "
    "existed for 3) — don't hedge or undersell the candidate just because a "
    "literal requirement looks larger than their exact background. Adding "
    "relevant tools/technologies the JD asks for (e.g. Kubernetes, AWS, "
    "gRPC, Docker, CI/CD) alongside what's explicitly in their background "
    "is fine, even if not literally mentioned in the source.\n\n"
    "Hard lines — never invent:\n"
    "- Employers, job titles the candidate never held, degrees, or "
    "certifications that don't exist.\n"
    "- A second job or employment period that isn't in the source "
    "background — if the background describes one role, the resume "
    "describes one role, not a fabricated job history.\n"
    "- Specific numbers or metrics not present in the source (uptime "
    "percentages, response-time improvements, bug-reduction rates, etc.) — "
    "only use a number if the candidate's background actually contains it.\n\n"
    "Output the resume as plain text."
)


async def draft_resume(state: PrepareState) -> dict:
    user_prompt = (
        f"Candidate background:\n{state['resume_content']}\n\n"
        f"Target job description:\n{state['job_description']}"
    )
    messages = [SystemMessage(content=RESUME_AGENT_PROMPT), HumanMessage(content=user_prompt)]
    result = await call_llm(messages)
    return {"resume_output": extract_text(result.content), "status": "resume_drafted"}
