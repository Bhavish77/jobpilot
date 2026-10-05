"""State schema for the Interview Prep graph.

Extends MessagesState (this graph *is* a conversation, unlike PrepareState)
with the extra fields the conversation needs to carry alongside the message
history: the job/candidate context, and the curriculum once generated.
"""

from langgraph.graph import MessagesState


class InterviewState(MessagesState):
    job_description: str
    resume_content: str

    # Set once by generate_curriculum, then persists across every later
    # turn via the checkpointer — that's what lets the conditional edge in
    # interview_graph.py skip regenerating it on turn 2+.
    curriculum: str
