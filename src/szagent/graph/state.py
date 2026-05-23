from typing import TypedDict

from typing_extensions import NotRequired


class AgentState(TypedDict):
    messages: list[str]
    next_step: NotRequired[str]
