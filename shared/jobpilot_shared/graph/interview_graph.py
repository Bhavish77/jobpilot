"""Interview Prep graph — Phase 2.

Chunk 5b's conditional generate-or-skip logic moved out in chunk 6: the
curriculum is now always generated during /prepare (see prepare_graph.py's
parallel fan-out), never lazily on a thread's first message. So this graph
goes back to a single node — `interview_turn` just expects `curriculum`
to already be present in the state the router hands it, read from the
Application row rather than generated here.

Still uncompiled here (see chunk 5a) — main.py's lifespan compiles it with
the checkpointer attached once that's available at startup.
"""

from langgraph.graph import END, START, StateGraph

from jobpilot_shared.graph.agents.interview_prep import interview_turn
from jobpilot_shared.graph.interview_state import InterviewState

builder = StateGraph(InterviewState)
builder.add_node("interview_turn", interview_turn)
builder.add_edge(START, "interview_turn")
builder.add_edge("interview_turn", END)
