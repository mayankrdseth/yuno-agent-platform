from typing import Any
from typing_extensions import TypedDict


class WorkflowState(TypedDict):
    user_input: str
    current_step: str
    research_notes: str
    final_response: str
    status: str
    # LLM routing
    routing_decision: str
    routing_reason: str
    # Tool execution log
    tool_calls: list[dict[str, Any]]
