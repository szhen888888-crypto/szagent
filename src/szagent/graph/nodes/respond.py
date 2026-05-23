from szagent.graph.state import AgentState


def respond(state: AgentState) -> AgentState:
    last_message = state["messages"][-1] if state["messages"] else ""
    return {"messages": [*state["messages"], f"Received: {last_message}"]}
