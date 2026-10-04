"""Cover Letter Agent — Phase 2, chunk 4.

Runs sequentially after the Resume Agent (see prepare_graph.py's edges) and
reads `resume_output` from state — it drafts a letter that's *consistent*
with what the resume just emphasized, not an independent take on the
candidate, per the design doc's "cover letter references what the resume
emphasized."
"""

from langchain_core.messages import HumanMessage, SystemMessage

from app.graph.llm import call_llm, extract_text
from app.graph.prepare_state import PrepareState

COVER_LETTER_AGENT_PROMPT = (
    "You are a cover-letter-writing assistant. Given a candidate's tailored "
    "resume for a specific job and the job description, write a cover "
    "letter that complements the resume rather than repeating it — cover "
    "the same ground the resume emphasizes, but use the letter to explain "
    "motivation and fit, framed forward-looking (what the candidate would "
    "bring to this role), not just a recap of the past.\n\n"
    "Stay consistent with the resume you were given — don't introduce "
    "employers, titles, degrees, or certifications that aren't in it. "
    "Output the cover letter as plain text."
)


async def draft_cover_letter(state: PrepareState) -> dict:
    user_prompt = (
        f"Tailored resume:\n{state['resume_output']}\n\n"
        f"Job description:\n{state['job_description']}"
    )
    messages = [SystemMessage(content=COVER_LETTER_AGENT_PROMPT), HumanMessage(content=user_prompt)]
    result = await call_llm(messages)
    return {"cover_letter_output": extract_text(result.content), "status": "cover_letter_drafted"}
