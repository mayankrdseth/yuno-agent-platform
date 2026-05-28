from typing import TypedDict


class TokenUsage(TypedDict):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class WorkflowState(TypedDict):
    user_input: str
    current_step: str
    research_notes: str
    final_response: str
    status: str
    routing_decision: str
    routing_reason: str
    tool_calls: list[dict]
    token_usage: TokenUsage
