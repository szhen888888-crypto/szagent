from langgraph.graph import END, StateGraph


from szagent.graph.edges import should_continue
from szagent.graph.nodes import respond
from szagent.graph.state import AgentState


def build_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("respond", respond)
    workflow.set_entry_point("respond")
    workflow.add_conditional_edges("respond", should_continue, {"end": END})
    return workflow.compile()
