from typing import Literal

from szagent.graph.state import AgentState


def should_continue(state: AgentState) -> Literal["end"]:
    return "end"
