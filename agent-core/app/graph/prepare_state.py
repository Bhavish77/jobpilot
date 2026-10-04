"""State schema for the Prepare pipeline graph — separate from `graph.py`'s
`MessagesState`, because this pipeline isn't a conversation. It's triggered
by the "Prepare" button (Discover screen), not a chat message, and its
steps pass structured data to each other, not a growing message list.
"""

from typing import TypedDict


class PrepareState(TypedDict):
    user_id: str
    job_description: str
    resume_content: str

    # Set by the resume-quality gate (chunk 2).
    quality_ok: bool
    rejection_reason: str | None

    # Set by the Resume Agent (chunk 3).
    resume_output: str

    # Set by the Cover Letter Agent (chunk 4).
    cover_letter_output: str

    # Set by generate_curriculum (chunk 6), running in parallel with
    # draft_resume/draft_cover_letter — same node function Interview Prep's
    # graph uses, reused as-is since both state schemas share the
    # resume_content/job_description field names it reads.
    curriculum: str

    # Set by review_and_revise (chunk 8) — kept separate from
    # resume_output/cover_letter_output until await_review_approval decides
    # whether to accept them, so the human-in-the-loop step has both the
    # original and the proposed revision to compare.
    proposed_resume: str
    proposed_cover_letter: str

    # Coarse progress marker, useful for tests/debugging until real agent
    # output fields (resume_output, cover_letter_output, ...) land in later
    # chunks.
    status: str
