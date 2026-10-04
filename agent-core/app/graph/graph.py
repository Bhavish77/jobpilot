"""Phase 2, chunk 1 — the chatbot as a LangGraph `StateGraph`.

Deliberately the smallest possible graph: one node, doing exactly what
`chat.py`'s direct `llm.ainvoke(...)` call did in Phase 1. Same behavior,
new plumbing — later chunks add the supervisor, specialist agents, and
Postgres checkpointing on top of this same skeleton without changing this
node's shape.
"""

from langchain_core.messages import SystemMessage
from langgraph.graph import END, START, MessagesState, StateGraph

from app.graph.llm import call_llm

SYSTEM_PROMPT = (
    "You are JobPilot's assistant. You help the user with their job search — "
    "answering questions about their resume, target roles, and the application "
    "process. You never submit job applications yourself; you only prepare "
    "materials and advice for the user to act on."
)


async def generate_reply(state: MessagesState) -> dict:
    """The one node in this graph. Takes the conversation so far, calls the
    LLM once (via the shared, rate-limit-enforcing call_llm), and returns
    the new message to append."""
    messages = [SystemMessage(content=SYSTEM_PROMPT), *state["messages"]]
    result = await call_llm(messages)
    return {"messages": [result]}


builder = StateGraph(MessagesState)
builder.add_node("generate_reply", generate_reply)
builder.add_edge(START, "generate_reply")
builder.add_edge("generate_reply", END)

graph = builder.compile()
